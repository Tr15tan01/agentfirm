"""Model Gateway: capability → configured route → first healthy provider.

Agents never name models. The gateway resolves the route chosen by super-admins
(agent-version → org → platform), tries candidates in order with retries for transient
errors, opens a per-provider circuit after repeated failures, and reports the model
ACTUALLY used (incl. fallback index) for events and metering.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, TypeVar
from uuid import UUID

import httpx
from pydantic import BaseModel, ValidationError

from agentfirm.core.config import get_settings
from agentfirm.core.db import DbContext, apply_context, sessionmaker
from agentfirm.modules.gateway.service import ModelOut, decrypt_credential, resolve_route

from . import simulated
from .adapters import ADAPTERS
from .types import Message, ModelRequest, ModelResponse, ModelUnavailable, ProviderError

T = TypeVar("T", bound=BaseModel)
OnCall = Callable[[ModelResponse, str], Awaitable[None]]


@dataclass
class _Breaker:
    failures: int = 0
    open_until: float = 0.0


@dataclass
class ModelGateway:
    http: httpx.AsyncClient = field(default_factory=lambda: httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10)))
    breaker_threshold: int = 3
    breaker_seconds: float = 30.0
    retries: int = 2
    _breakers: dict[str, _Breaker] = field(default_factory=dict)

    def reset_breakers(self) -> None:
        """Close every circuit (eval isolation; ops tooling)."""
        self._breakers.clear()

    def _available(self, provider: str) -> bool:
        b = self._breakers.get(provider)
        return b is None or b.open_until <= time.monotonic()

    def _record(self, provider: str, ok: bool) -> None:
        b = self._breakers.setdefault(provider, _Breaker())
        if ok:
            b.failures, b.open_until = 0, 0.0
        else:
            b.failures += 1
            if b.failures >= self.breaker_threshold:
                b.open_until = time.monotonic() + self.breaker_seconds

    async def _candidates(self, capability: str, org_id: UUID, agent_version_id: UUID | None) -> list[ModelOut]:
        async with sessionmaker()() as s, s.begin():
            await apply_context(s, DbContext(org_id=org_id))
            return await resolve_route(s, capability, org_id=org_id, agent_version_id=agent_version_id)

    async def _api_key(self, provider: str) -> str | None:
        async with sessionmaker()() as s, s.begin():
            await apply_context(s, DbContext(platform_admin=True))
            return await decrypt_credential(s, provider)

    async def _base_url(self, provider: str) -> str | None:
        from sqlalchemy import select

        from agentfirm.modules.gateway.models import ModelProvider

        async with sessionmaker()() as s, s.begin():
            return await s.scalar(select(ModelProvider.base_url).where(ModelProvider.key == provider))

    async def complete(self, *, capability: str, request: ModelRequest, org_id: UUID, agent_version_id: UUID | None, on_call: OnCall) -> ModelResponse:
        settings = get_settings()
        candidates = await self._candidates(capability, org_id, agent_version_id)
        if not candidates:
            raise ModelUnavailable(f"No route configured for capability '{capability}'")
        errors: list[str] = []
        for index, model in enumerate(candidates):
            if not self._available(model.provider):
                errors.append(f"{model.provider}: circuit open")
                continue
            for attempt in range(self.retries + 1):
                try:
                    if settings.gateway_mode == "simulated":
                        if model.provider in simulated.FAILING_PROVIDERS:
                            raise ProviderError(f"{model.provider}: simulated outage", retriable=False, status=503)
                        resp = await simulated.complete(request, latency_ms=settings.simulated_latency_ms)
                    else:
                        resp = await ADAPTERS[model.provider].complete(
                            self.http, request, model=model.name, api_key=await self._api_key(model.provider), base_url=await self._base_url(model.provider)
                        )
                    self._record(model.provider, True)
                    resp.provider, resp.model, resp.fallback_index = model.provider, model.name, index
                    resp.cost_usd = _cost(model, resp)
                    await on_call(resp, capability)
                    return resp
                except ProviderError as exc:
                    self._record(model.provider, False)
                    errors.append(str(exc))
                    if not exc.retriable or attempt == self.retries:
                        break
                    await asyncio.sleep(min(8.0, 0.5 * 2**attempt))
                except httpx.HTTPError as exc:
                    self._record(model.provider, False)
                    errors.append(f"{model.provider}: {exc.__class__.__name__}")
                    if attempt == self.retries:
                        break
                    await asyncio.sleep(min(8.0, 0.5 * 2**attempt))
        raise ModelUnavailable("; ".join(errors[-6:]))

    async def structured(self, *, capability: str, request: ModelRequest, schema: type[T], org_id: UUID, agent_version_id: UUID | None, on_call: OnCall) -> T:
        """JSON output validated into `schema`, with one repair round-trip on invalid output."""
        request.json_schema = schema.model_json_schema()
        resp = await self.complete(capability=capability, request=request, org_id=org_id, agent_version_id=agent_version_id, on_call=on_call)
        try:
            return schema.model_validate(parse_json(resp.text))
        except (ValueError, ValidationError) as exc:
            request.messages = [
                *request.messages,
                Message("assistant", resp.text[:4000]),
                Message("user", f"That was not valid JSON for the schema ({str(exc)[:300]}). Return only the corrected JSON."),
            ]
            resp = await self.complete(capability=capability, request=request, org_id=org_id, agent_version_id=agent_version_id, on_call=on_call)
            return schema.model_validate(parse_json(resp.text))


FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.S)


def parse_json(text: str) -> Any:
    text = FENCE.sub("", text.strip())
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=0)
    return json.loads(text[start:])


def _cost(model: ModelOut, resp: ModelResponse) -> Decimal:
    pin = model.price_in_per_1m or Decimal(0)
    pout = model.price_out_per_1m or Decimal(0)
    cost = (Decimal(resp.tokens_in) * pin + Decimal(resp.tokens_out) * pout) / Decimal(1_000_000)
    return cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def credits_for(resp: ModelResponse) -> int:
    """1 credit = $0.01 of provider cost (configurable); self-hosted models: 1 credit per 2k tokens. Minimum 1."""
    if resp.cost_usd > 0:
        return max(1, int((resp.cost_usd / Decimal(str(get_settings().usd_per_credit))).to_integral_value(rounding="ROUND_CEILING")))
    return max(1, (resp.tokens_in + resp.tokens_out) // 2000)
