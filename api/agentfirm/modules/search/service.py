"""Web-search settings for super-admins, and the runtime resolver the research tools use.

Resolution (per search): the admin's choice wins; with no choice saved (provider NULL) the
environment defaults apply (AGENTFIRM_SEARCH_PROVIDER / AGENTFIRM_BRAVE_API_KEY). The Brave key
is stored envelope-encrypted; Gemini grounding re-uses the Gemini provider's key.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentfirm.core.config import get_settings
from agentfirm.core.crypto import Sealed, open_sealed, seal
from agentfirm.core.deps import Principal
from agentfirm.core.errors import Unprocessable
from agentfirm.modules.audit.service import record
from agentfirm.modules.gateway.models import ModelProvider
from agentfirm.modules.gateway.service import decrypt_credential

from .models import SearchCredential, SearchSettings

SearchProvider = Literal["brave", "gemini", "none"]
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"


def _aad() -> bytes:
    return b"search:brave"


class SearchSettingsIn(BaseModel):
    provider: SearchProvider
    fallback: SearchProvider = "none"
    gemini_model: str = Field(default=DEFAULT_GEMINI_MODEL, min_length=3, max_length=120, pattern=r"^[A-Za-z0-9._-]+$")


class BraveKeyIn(BaseModel):
    api_key: str = Field(min_length=8, max_length=512)


class SearchTestIn(BaseModel):
    provider: Literal["brave", "gemini"]
    query: str = Field(default="latest news about open source AI", min_length=2, max_length=200)


class KeyState(BaseModel):
    configured: bool
    last4: str | None = None
    source: Literal["admin", "environment", "gemini_provider"] | None = None


class SearchSettingsOut(BaseModel):
    provider: SearchProvider
    fallback: SearchProvider
    gemini_model: str
    #: True while no explicit choice is saved and the environment defaults are in force.
    using_environment_defaults: bool
    brave: KeyState
    gemini: KeyState
    updated_at: datetime | None = None


class SearchTestOut(BaseModel):
    ok: bool
    provider: str
    results: int
    sample: list[str]
    error: str | None = None


@dataclass(slots=True)
class SearchConfig:
    provider: str
    fallback: str
    gemini_model: str
    brave_key: str | None
    gemini_key: str | None
    gemini_base_url: str | None


async def _row(session: AsyncSession) -> SearchSettings | None:
    return (await session.execute(select(SearchSettings).where(SearchSettings.id == 1))).scalar_one_or_none()


async def _brave_credential(session: AsyncSession) -> SearchCredential | None:
    return (
        await session.execute(select(SearchCredential).where(SearchCredential.provider == "brave", SearchCredential.revoked_at.is_(None)))
    ).scalar_one_or_none()


async def _brave_key(session: AsyncSession) -> tuple[str | None, str | None, str | None]:
    """(key, last4, source)"""
    cred = await _brave_credential(session)
    if cred is not None:
        key = open_sealed(Sealed(cred.ciphertext, cred.nonce, cred.wrapped_key, cred.key_nonce, cred.key_id, cred.last4), aad=_aad())
        return key, cred.last4, "admin"
    env = get_settings().brave_api_key
    if env:
        return env, env[-4:], "environment"
    return None, None, None


async def load_config(session: AsyncSession) -> SearchConfig:
    env = get_settings()
    row = await _row(session)
    brave_key, _, _ = await _brave_key(session)
    gemini_key = await decrypt_credential(session, "gemini")
    gemini_base = await session.scalar(select(ModelProvider.base_url).where(ModelProvider.key == "gemini"))
    return SearchConfig(
        provider=(row.provider if row and row.provider else env.search_provider),
        fallback=(row.fallback if row and row.fallback else "none"),
        gemini_model=(row.gemini_model if row else DEFAULT_GEMINI_MODEL),
        brave_key=brave_key,
        gemini_key=gemini_key,
        gemini_base_url=gemini_base,
    )


async def get_settings_out(session: AsyncSession) -> SearchSettingsOut:
    row = await _row(session)
    cfg = await load_config(session)
    _, last4, source = await _brave_key(session)
    gem_last4 = None
    if cfg.gemini_key:
        gem_last4 = cfg.gemini_key[-4:]
    return SearchSettingsOut(
        provider=cfg.provider,  # type: ignore[arg-type]
        fallback=cfg.fallback,  # type: ignore[arg-type]
        gemini_model=cfg.gemini_model,
        using_environment_defaults=not (row and row.provider),
        brave=KeyState(configured=bool(cfg.brave_key), last4=last4, source=source),  # type: ignore[arg-type]
        gemini=KeyState(configured=bool(cfg.gemini_key), last4=gem_last4, source="gemini_provider" if cfg.gemini_key else None),
        updated_at=row.updated_at if row else None,
    )


async def update_settings(session: AsyncSession, admin: Principal, body: SearchSettingsIn) -> SearchSettingsOut:
    if body.fallback == body.provider and body.provider != "none":
        raise Unprocessable("The fallback must be a different provider than the primary.")
    cfg = await load_config(session)
    for name in {body.provider, body.fallback} - {"none"}:
        have = cfg.brave_key if name == "brave" else cfg.gemini_key
        if not have:
            hint = "Save a Brave API key first." if name == "brave" else "Save a Gemini API key under Model providers first."
            raise Unprocessable(f"Cannot use {name} for search yet. {hint}")
    row = await _row(session)
    before = {"provider": row.provider if row else None, "fallback": row.fallback if row else None, "gemini_model": row.gemini_model if row else None}
    if row is None:
        row = SearchSettings(id=1)
        session.add(row)
    row.provider, row.fallback, row.gemini_model = body.provider, body.fallback, body.gemini_model
    row.updated_by, row.updated_at = admin.user_id, datetime.now(UTC)
    await session.flush()
    await record(
        session,
        action="search.settings_updated",
        target_type="search_settings",
        target_id=None,
        actor=admin,
        before=before,
        after=body.model_dump(mode="json"),
        platform=True,
    )
    return await get_settings_out(session)


async def set_brave_key(session: AsyncSession, admin: Principal, body: BraveKeyIn) -> SearchSettingsOut:
    now = datetime.now(UTC)
    old = await _brave_credential(session)
    if old is not None:
        old.revoked_at = now
        await session.flush()  # the partial unique index allows only one active key
    s = seal(body.api_key, aad=_aad())
    session.add(
        SearchCredential(
            provider="brave",
            ciphertext=s.ciphertext,
            nonce=s.nonce,
            wrapped_key=s.wrapped_key,
            key_nonce=s.key_nonce,
            key_id=s.key_id,
            last4=s.last4,
            created_by=admin.user_id,
        )
    )
    await session.flush()
    await record(
        session,
        action="search.credential_rotated",
        target_type="search_settings",
        target_id=None,
        actor=admin,
        after={"provider": "brave", "last4": s.last4},
        platform=True,
    )
    return await get_settings_out(session)


async def clear_brave_key(session: AsyncSession, admin: Principal) -> SearchSettingsOut:
    old = await _brave_credential(session)
    if old is not None:
        old.revoked_at = datetime.now(UTC)
        await session.flush()
        await record(
            session, action="search.credential_removed", target_type="search_settings", target_id=None, actor=admin, after={"provider": "brave"}, platform=True
        )
    return await get_settings_out(session)


async def run_test(session: AsyncSession, admin: Principal, body: SearchTestIn) -> SearchTestOut:
    """Runs one real query against the chosen back-end so the admin sees whether it works."""
    from agentfirm.runtime.tools import search_providers as sp
    from agentfirm.runtime.tools.web import WebError

    cfg = await load_config(session)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            if body.provider == "brave":
                if not cfg.brave_key:
                    raise WebError("No Brave API key is saved.")
                found = await sp.brave_search(client, cfg.brave_key, body.query, 5)
            else:
                if not cfg.gemini_key:
                    raise WebError("No Gemini API key is saved.")
                found = await sp.gemini_grounded_search(client, cfg.gemini_key, cfg.gemini_model, body.query, 5, cfg.gemini_base_url)
        out = SearchTestOut(ok=True, provider=body.provider, results=len(found), sample=[r["title"][:80] for r in found[:3]])
    except (WebError, httpx.HTTPError) as exc:
        out = SearchTestOut(ok=False, provider=body.provider, results=0, sample=[], error=str(exc)[:300] or type(exc).__name__)
    await record(
        session,
        action="search.tested",
        target_type="search_settings",
        target_id=None,
        actor=admin,
        after={"provider": body.provider, "ok": out.ok},
        platform=True,
    )
    return out
