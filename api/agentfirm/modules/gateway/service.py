"""Model Gateway configuration (super-admin): providers, encrypted credentials,
model catalog and per-capability routing (primary + ordered fallbacks).

`resolve_route()` is what the Agent Engine will call in Phase 4: agents ask for a
capability ("reasoning", "code", …), never a model name."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentfirm.core.crypto import Sealed, open_sealed, seal
from agentfirm.core.deps import Principal
from agentfirm.core.errors import NotFound, Unprocessable
from agentfirm.modules.audit.service import record
from agentfirm.modules.identity.models import Organization

from .models import CAPABILITIES, Model, ModelProvider, ModelRoute, ProviderCredential

# ── Schemas ──────────────────────────────────────────────────────────────────


class ProviderOut(BaseModel):
    id: UUID
    key: str
    name: str
    kind: str
    base_url: str | None
    enabled: bool
    credential_last4: str | None = Field(description="Only the last 4 characters are ever returned")
    credential_set_at: datetime | None


class ProviderPatch(BaseModel):
    enabled: bool | None = None
    base_url: HttpUrl | None = None


class CredentialIn(BaseModel):
    api_key: str = Field(min_length=8, max_length=4096)


class ModelOut(BaseModel):
    id: UUID
    provider: str
    name: str
    label: str
    capabilities: list[str]
    price_in_per_1m: Decimal | None
    price_out_per_1m: Decimal | None
    enabled: bool


class ModelIn(BaseModel):
    provider: str
    name: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=120)
    capabilities: list[str] = Field(min_length=1)
    price_in_per_1m: Decimal | None = Field(default=None, ge=0)
    price_out_per_1m: Decimal | None = Field(default=None, ge=0)


class RouteIn(BaseModel):
    primary: UUID
    fallbacks: list[UUID] = Field(default_factory=list, max_length=3)
    params: dict[str, Any] = Field(default_factory=dict)


class RouteOut(BaseModel):
    capability: str
    primary: ModelOut | None
    fallbacks: list[ModelOut]
    params: dict[str, Any]


class OrgSummary(BaseModel):
    id: UUID
    name: str
    slug: str
    created_at: datetime


# ── Providers & credentials ──────────────────────────────────────────────────


def _aad(provider_id: UUID) -> bytes:
    # Binds ciphertext to its provider row: a ciphertext copied to another provider won't decrypt.
    return f"provider:{provider_id}".encode()


async def _active_credentials(session: AsyncSession) -> dict[UUID, ProviderCredential]:
    rows = (await session.execute(select(ProviderCredential).where(ProviderCredential.revoked_at.is_(None)))).scalars()
    return {c.provider_id: c for c in rows}


async def list_providers(session: AsyncSession) -> list[ProviderOut]:
    creds = await _active_credentials(session)
    out = []
    for p in (await session.execute(select(ModelProvider).order_by(ModelProvider.name))).scalars():
        c = creds.get(p.id)
        out.append(
            ProviderOut(
                id=p.id,
                key=p.key,
                name=p.name,
                kind=p.kind,
                base_url=p.base_url,
                enabled=p.enabled,
                credential_last4=c.last4 if c else None,
                credential_set_at=c.created_at if c else None,
            )
        )
    return out


async def _provider(session: AsyncSession, provider_id: UUID) -> ModelProvider:
    p = await session.get(ModelProvider, provider_id)
    if p is None:
        raise NotFound("Provider not found.")
    return p


async def patch_provider(session: AsyncSession, admin: Principal, provider_id: UUID, body: ProviderPatch) -> ProviderOut:
    p = await _provider(session, provider_id)
    before = {"enabled": p.enabled, "base_url": p.base_url}
    if body.enabled is not None:
        p.enabled = body.enabled
    if body.base_url is not None:
        p.base_url = str(body.base_url)
    await record(
        session,
        action="gateway.provider_updated",
        target_type="model_provider",
        target_id=p.id,
        actor=admin,
        before=before,
        after={"enabled": p.enabled, "base_url": p.base_url},
        platform=True,
    )
    await session.flush()
    return next(x for x in await list_providers(session) if x.id == p.id)


async def set_credential(session: AsyncSession, admin: Principal, provider_id: UUID, body: CredentialIn) -> ProviderOut:
    p = await _provider(session, provider_id)
    now = datetime.now(UTC)
    for old in (
        await session.execute(select(ProviderCredential).where(ProviderCredential.provider_id == p.id, ProviderCredential.revoked_at.is_(None)))
    ).scalars():
        old.revoked_at = now
    s = seal(body.api_key, aad=_aad(p.id))
    session.add(
        ProviderCredential(
            provider_id=p.id,
            ciphertext=s.ciphertext,
            nonce=s.nonce,
            wrapped_key=s.wrapped_key,
            key_nonce=s.key_nonce,
            key_id=s.key_id,
            last4=s.last4,
            created_by=admin.user_id,
        )
    )
    # Never log the secret — only that it changed and its last 4 characters.
    await record(
        session, action="gateway.credential_rotated", target_type="model_provider", target_id=p.id, actor=admin, after={"last4": s.last4}, platform=True
    )
    await session.flush()
    return next(x for x in await list_providers(session) if x.id == p.id)


async def decrypt_credential(session: AsyncSession, provider_key: str) -> str | None:
    """For the Model Gateway (Phase 4) only — never exposed through HTTP."""
    row = (
        await session.execute(
            select(ProviderCredential)
            .join(ModelProvider, ModelProvider.id == ProviderCredential.provider_id)
            .where(ModelProvider.key == provider_key, ProviderCredential.revoked_at.is_(None))
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return open_sealed(Sealed(row.ciphertext, row.nonce, row.wrapped_key, row.key_nonce, row.key_id, row.last4), aad=_aad(row.provider_id))


# ── Models ───────────────────────────────────────────────────────────────────


def _model_out(m: Model, provider_key: str) -> ModelOut:
    return ModelOut(
        id=m.id,
        provider=provider_key,
        name=m.name,
        label=m.label,
        capabilities=list(m.capabilities),
        price_in_per_1m=m.price_in_per_1m,
        price_out_per_1m=m.price_out_per_1m,
        enabled=m.enabled,
    )


async def list_models(session: AsyncSession) -> list[ModelOut]:
    rows = (
        await session.execute(
            select(Model, ModelProvider.key).join(ModelProvider, ModelProvider.id == Model.provider_id).order_by(ModelProvider.key, Model.label)
        )
    ).all()
    return [_model_out(m, k) for m, k in rows]


async def create_model(session: AsyncSession, admin: Principal, body: ModelIn) -> ModelOut:
    bad = set(body.capabilities) - set(CAPABILITIES)
    if bad:
        raise Unprocessable(f"Unknown capabilities: {', '.join(sorted(bad))}")
    p = (await session.execute(select(ModelProvider).where(ModelProvider.key == body.provider))).scalar_one_or_none()
    if p is None:
        raise Unprocessable("Unknown provider.")
    m = Model(
        provider_id=p.id,
        name=body.name,
        label=body.label,
        capabilities=sorted(set(body.capabilities)),
        price_in_per_1m=body.price_in_per_1m,
        price_out_per_1m=body.price_out_per_1m,
    )
    session.add(m)
    await session.flush()
    await record(session, action="gateway.model_created", target_type="model", target_id=m.id, actor=admin, after=body.model_dump(mode="json"), platform=True)
    return _model_out(m, p.key)


# ── Routing ──────────────────────────────────────────────────────────────────


async def _route_rows(session: AsyncSession, scope: str, scope_id: UUID | None) -> dict[str, list[tuple[ModelRoute, Model, str]]]:
    q = (
        select(ModelRoute, Model, ModelProvider.key)
        .join(Model, Model.id == ModelRoute.model_id)
        .join(ModelProvider, ModelProvider.id == Model.provider_id)
        .where(ModelRoute.scope == scope)
        .order_by(ModelRoute.capability, ModelRoute.priority)
    )
    q = q.where(ModelRoute.scope_id.is_(None)) if scope_id is None else q.where(ModelRoute.scope_id == scope_id)
    out: dict[str, list[tuple[ModelRoute, Model, str]]] = {}
    for r, m, k in (await session.execute(q)).all():
        out.setdefault(r.capability, []).append((r, m, k))
    return out


def _route_out(cap: str, rows: list[tuple[ModelRoute, Model, str]]) -> RouteOut:
    primary = next(((m, k) for r, m, k in rows if r.priority == 0), None)
    return RouteOut(
        capability=cap,
        primary=_model_out(*primary) if primary else None,
        fallbacks=[_model_out(m, k) for r, m, k in rows if r.priority > 0],
        params=next((r.params for r, _, _ in rows if r.priority == 0), {}),
    )


async def list_routes(session: AsyncSession) -> list[RouteOut]:
    rows = await _route_rows(session, "platform", None)
    return [_route_out(cap, rows.get(cap, [])) for cap in CAPABILITIES]


async def set_route(session: AsyncSession, admin: Principal, capability: str, body: RouteIn) -> RouteOut:
    if capability not in CAPABILITIES:
        raise NotFound("Unknown capability.")
    chain = [body.primary, *body.fallbacks]
    if len(set(chain)) != len(chain):
        raise Unprocessable("A model can appear only once in a route.", code="duplicate_model")
    models = {
        m.id: (m, k)
        for m, k in (
            await session.execute(select(Model, ModelProvider.key).join(ModelProvider, ModelProvider.id == Model.provider_id).where(Model.id.in_(chain)))
        ).all()
    }
    for mid in chain:
        if mid not in models:
            raise Unprocessable(f"Model {mid} does not exist.", code="unknown_model")
        m, _ = models[mid]
        if capability not in m.capabilities:
            raise Unprocessable(f"{m.label} does not support '{capability}'.", code="capability_mismatch")
        if not m.enabled:
            raise Unprocessable(f"{m.label} is disabled.", code="model_disabled")

    before = _route_out(capability, (await _route_rows(session, "platform", None)).get(capability, []))
    await session.execute(delete(ModelRoute).where(ModelRoute.scope == "platform", ModelRoute.scope_id.is_(None), ModelRoute.capability == capability))
    for prio, mid in enumerate(chain):
        session.add(
            ModelRoute(
                scope="platform",
                scope_id=None,
                capability=capability,
                priority=prio,
                model_id=mid,
                params=body.params if prio == 0 else {},
                updated_by=admin.user_id,
            )
        )
    await session.flush()
    after = _route_out(capability, (await _route_rows(session, "platform", None)).get(capability, []))
    await record(
        session,
        action="gateway.route_updated",
        target_type="model_route",
        target_id=capability,
        actor=admin,
        platform=True,
        before={"chain": [m.name for m in ([before.primary] if before.primary else []) + before.fallbacks]},
        after={"chain": [m.name for m in ([after.primary] if after.primary else []) + after.fallbacks], "params": body.params},
    )
    return after


async def resolve_route(session: AsyncSession, capability: str, *, org_id: UUID | None = None, agent_version_id: UUID | None = None) -> list[ModelOut]:
    """Ordered candidate models for a capability: agent-version override → org override → platform.
    Disabled models/providers are skipped; the Gateway then tries them in order."""
    for scope, sid in (("agent_version", agent_version_id), ("org", org_id), ("platform", None)):
        if scope != "platform" and sid is None:
            continue
        rows = (await _route_rows(session, scope, sid)).get(capability)
        if rows:
            enabled = {p.key for p in (await session.execute(select(ModelProvider).where(ModelProvider.enabled.is_(True)))).scalars()}
            return [_model_out(m, k) for _, m, k in rows if m.enabled and k in enabled]
    return []


async def list_organizations(session: AsyncSession) -> list[OrgSummary]:
    rows = (await session.execute(select(Organization).order_by(Organization.created_at.desc()))).scalars()
    return [OrgSummary(id=o.id, name=o.name, slug=o.slug, created_at=o.created_at) for o in rows]
