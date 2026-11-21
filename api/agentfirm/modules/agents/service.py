from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentfirm.core.deps import Principal
from agentfirm.core.errors import NotFound

from .models import Agent, AgentVersion, OrgAgentSetting


class ToolOut(BaseModel):
    key: str
    description: str
    side_effect: str
    approval: str


class ModelChoice(BaseModel):
    capability: str
    model: str | None
    provider: str | None


class UsageStats(BaseModel):
    runs_30d: int = 0
    success_rate: float | None = None
    avg_duration_s: float | None = None
    credits_30d: int = 0


class RecentRun(BaseModel):
    task_id: UUID
    execution_id: UUID
    title: str
    status: str
    queued_at: datetime
    finished_at: datetime | None


class AgentOut(BaseModel):
    key: str
    name: str
    description: str
    version: str
    enabled: bool
    manifest: dict[str, Any]
    #: Only on GET /agents/{key}: the workspace's effective view of this agent.
    tools: list[ToolOut] | None = None
    models: list[ModelChoice] | None = None
    usage: UsageStats | None = None
    recent: list[RecentRun] | None = None


async def _rows(session: AsyncSession, principal: Principal, key: str | None = None) -> list[AgentOut]:
    q = (
        select(Agent, AgentVersion, OrgAgentSetting.enabled)
        .join(AgentVersion, (AgentVersion.agent_id == Agent.id) & AgentVersion.is_current.is_(True))
        .outerjoin(OrgAgentSetting, (OrgAgentSetting.agent_id == Agent.id) & (OrgAgentSetting.org_id == principal.org_id))
        .where(Agent.is_enabled.is_(True))
        .order_by(Agent.name)
    )
    if key:
        q = q.where(Agent.key == key)
    out: list[AgentOut] = []
    for agent, version, enabled in (await session.execute(q)).all():
        out.append(
            AgentOut(
                key=agent.key, name=agent.name, description=agent.description, version=version.version, enabled=enabled is not False, manifest=version.manifest
            )
        )
    return out


async def list_agents(session: AsyncSession, principal: Principal) -> list[AgentOut]:
    return await _rows(session, principal)


async def get_agent(session: AsyncSession, principal: Principal, key: str) -> AgentOut:
    rows = await _rows(session, principal, key)
    if not rows:
        raise NotFound("Agent not found.")
    out = rows[0]
    m = out.manifest
    from agentfirm.agents.registry import registry

    reg = registry()
    tools = []
    for g in m.get("tools", []):
        spec = reg.tools.get(g.get("tool"))
        if spec is not None:
            tools.append(ToolOut(key=spec.key, description=spec.description, side_effect=spec.side_effect.value,
                                 approval=reg.effective_approval(key, spec.key).value if key in reg.agents else str(g.get("approval") or "auto")))
    from agentfirm.modules.gateway.service import resolve_route

    models = []
    for cap in (m.get("models") or {}).get("capabilities", []):
        chain = await resolve_route(session, cap, org_id=principal.org_id)
        models.append(ModelChoice(capability=cap, model=chain[0].label if chain else None, provider=chain[0].provider if chain else None))
    from agentfirm.modules.tasks.models import Task, TaskExecution

    since = datetime.now(UTC) - timedelta(days=30)
    agent_versions = select(AgentVersion.id).join(Agent, Agent.id == AgentVersion.agent_id).where(Agent.key == key)
    runs = (await session.execute(
        select(TaskExecution, Task.title).join(Task, (Task.id == TaskExecution.task_id) & (Task.org_id == TaskExecution.org_id))
        .where(TaskExecution.org_id == principal.org_id, TaskExecution.agent_version_id.in_(agent_versions), TaskExecution.queued_at >= since)
        .order_by(TaskExecution.queued_at.desc())
    )).all()
    finished = [e for e, _ in runs if e.status in ("completed", "failed")]
    ok = [e for e in finished if e.status == "completed" and (e.result or {}).get("status") == "completed"]
    durations = [(e.finished_at - e.started_at).total_seconds() for e in finished if e.started_at and e.finished_at]
    usage = UsageStats(runs_30d=len(runs), success_rate=round(len(ok) / len(finished), 3) if finished else None,
                       avg_duration_s=round(sum(durations) / len(durations), 1) if durations else None, credits_30d=sum(e.credits_used or 0 for e, _ in runs))
    recent = [RecentRun(task_id=e.task_id, execution_id=e.id, title=t, status=e.status, queued_at=e.queued_at, finished_at=e.finished_at) for e, t in runs[:8]]
    return out.model_copy(update={"tools": tools, "models": models, "usage": usage, "recent": recent})


async def current_version(session: AsyncSession, key: str) -> tuple[Agent, AgentVersion]:
    row = (
        await session.execute(
            select(Agent, AgentVersion)
            .join(AgentVersion, (AgentVersion.agent_id == Agent.id) & AgentVersion.is_current.is_(True))
            .where(Agent.key == key, Agent.is_enabled.is_(True))
        )
    ).one_or_none()
    if row is None:
        raise NotFound(f"Agent '{key}' not found.")
    return row[0], row[1]
