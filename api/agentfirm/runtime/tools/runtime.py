"""Tool Registry runtime: the single enforcement point for every tool call.

Order of checks (Agent Interface §6): grant → step declaration → permission → call cap →
approval → deny policy → budget → idempotent replay → timeout-wrapped execution →
persisted record + events.

Permission: an ordinary tool needs the *requesting user's* permission. An approval-gated
tool is authorised by the *approver*, who must hold both the side-effect approver class and
the tool's permission (checked when deciding and again here), so a member can request a
production deploy that an admin approves (ADR 0004).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from sqlalchemy import select

from agentfirm.agents.contracts import ApprovalPolicy, ErrorCode, SideEffect
from agentfirm.core.db import DbContext, apply_context, sessionmaker
from agentfirm.modules.tasks.models import ToolExecution

from ..context import ExecutionContext
from ..errors import StepError
from .impls import CURRENT_CALL, IMPLS
from .web import BlockedURL, WebError


def _summary(args: dict[str, Any]) -> str:
    shown = {k: (f"<{len(v)} chars>" if isinstance(v, str) and len(v) > 160 else v) for k, v in args.items() if k not in ("content",)}
    if "content" in args:
        shown["content"] = f"<{len(str(args['content']))} chars>"
    return json.dumps(shown, default=str)[:480]


_OVERRIDES: tuple[float, dict[str, str]] = (0.0, {})
OVERRIDE_TTL_S = 10.0


async def disabled_tools() -> dict[str, str]:
    """Platform kill-switches (super-admin), cached briefly; tool → reason."""
    global _OVERRIDES
    now = time.monotonic()
    if now - _OVERRIDES[0] > OVERRIDE_TTL_S:
        from sqlalchemy import select

        from agentfirm.core.db import sessionmaker
        from agentfirm.modules.governance.models import ToolOverride

        async with sessionmaker()() as s:
            rows = (await s.execute(select(ToolOverride.tool, ToolOverride.reason).where(ToolOverride.disabled.is_(True)))).all()
        _OVERRIDES = (now, {t: r for t, r in rows})
    return _OVERRIDES[1]


def reset_override_cache() -> None:
    global _OVERRIDES
    _OVERRIDES = (0.0, {})


async def invoke(ctx: ExecutionContext, key: str, args: dict[str, Any]) -> dict[str, Any]:
    if (reason := (await disabled_tools()).get(key)) is not None:
        await ctx.log("warn", f"{key} is turned off by the platform administrator: {reason}")
        raise StepError(ErrorCode.POLICY_VIOLATION, f"{key} is turned off by the platform administrator: {reason}")
    grant = next((g for g in ctx.manifest.tools if g.tool == key), None)
    if grant is None:
        raise StepError(ErrorCode.POLICY_VIOLATION, f"Tool {key} is not granted to {ctx.manifest.key}")
    if ctx.step_tools is not None and key not in ctx.step_tools:
        raise StepError(ErrorCode.POLICY_VIOLATION, f"Step {ctx.current_step} does not declare tool {key}")
    spec = ctx.registry.tools[key]
    gated = ctx.registry.effective_approval(ctx.manifest.key, key) == ApprovalPolicy.REQUIRE
    if gated and key in ctx.approved_tools:
        if spec.required_permission not in ctx.approver_permissions.get(key, frozenset()):
            raise StepError(ErrorCode.PERMISSION_DENIED, f"The approver no longer has {spec.required_permission} for {key}")
    elif spec.required_permission not in ctx.permissions:
        raise StepError(ErrorCode.PERMISSION_DENIED, f"Requesting user lacks {spec.required_permission} for {key}")
    if ctx.tool_counts[key] >= grant.max_calls_per_run:
        raise StepError(ErrorCode.BUDGET_EXCEEDED, f"Call cap reached for {key} ({grant.max_calls_per_run})")
    if gated and key not in ctx.approved_tools:
        raise StepError(ErrorCode.POLICY_VIOLATION, f"{key} requires an approved approval request first")
    if ctx.registry.effective_approval(ctx.manifest.key, key) == ApprovalPolicy.DENY:
        raise StepError(ErrorCode.PERMISSION_DENIED, f"{key} is denied by policy")
    ctx.check_budget()
    impl = IMPLS.get(key)
    if impl is None:
        raise StepError(ErrorCode.TOOL_ERROR, f"{key} has no implementation yet (planned)")

    ctx.tool_counts[key] += 1
    n = ctx.step_tool_counts[f"{ctx.current_step}:{key}"]
    ctx.step_tool_counts[f"{ctx.current_step}:{key}"] += 1
    idem = f"{ctx.execution_id}:{ctx.current_step}:{key}:{n}"
    side_effecting = spec.side_effect != SideEffect.NONE

    if side_effecting:
        async with sessionmaker()() as s, s.begin():
            await apply_context(s, DbContext(org_id=ctx.org_id))
            prior = (
                await s.execute(select(ToolExecution).where(ToolExecution.org_id == ctx.org_id, ToolExecution.idempotency_key == idem))
            ).scalar_one_or_none()
        if prior is not None and prior.status == "ok":
            await ctx.log("info", f"{key} replayed from idempotency record (no repeated side effect)")
            return prior.output or {}

    await ctx.emit(
        "tool.called", {"call_id": idem, "tool": key, "side_effect": spec.side_effect.value, "input_summary": _summary(args), "step": ctx.current_step}
    )
    started = time.monotonic()
    status, output, error = "ok", None, None
    try:
        token = CURRENT_CALL.set(idem)
        try:
            output = await asyncio.wait_for(impl(ctx, args), timeout=spec.timeout_seconds)
        finally:
            CURRENT_CALL.reset(token)
    except TimeoutError:
        status, error = "timeout", StepError(ErrorCode.TOOL_TIMEOUT, f"{key} timed out after {spec.timeout_seconds}s", retriable=True)
    except BlockedURL as exc:
        status, error = "blocked", StepError(ErrorCode.POLICY_VIOLATION, str(exc))
    except WebError as exc:
        status, error = "error", StepError(ErrorCode.TOOL_ERROR, str(exc), retriable=True)
    except StepError as exc:
        status, error = "error", exc
    duration = int((time.monotonic() - started) * 1000)

    async with sessionmaker()() as s, s.begin():
        await apply_context(s, DbContext(org_id=ctx.org_id))
        existing = (
            await s.execute(select(ToolExecution).where(ToolExecution.org_id == ctx.org_id, ToolExecution.idempotency_key == idem))
        ).scalar_one_or_none()
        if existing is None:
            s.add(
                ToolExecution(
                    org_id=ctx.org_id,
                    execution_id=ctx.execution_id,
                    idempotency_key=idem,
                    tool=key,
                    side_effect=spec.side_effect.value,
                    status=status,
                    input_summary=_summary(args),
                    output=output if side_effecting else None,
                    duration_ms=duration,
                )
            )
        else:
            existing.status, existing.output, existing.duration_ms = status, output if side_effecting else None, duration
    await ctx.emit("tool.result", {"call_id": idem, "tool": key, "status": status, "duration_ms": duration})
    from agentfirm.core.observability import TOOL_CALLS

    TOOL_CALLS.labels(key, status).inc()
    if error is not None:
        raise error
    return output or {}
