"""Database engine and the per-request unit of work.

Every request runs in ONE transaction. Before any query, the tenant context is
written with `set_config(..., is_local => true)` so PostgreSQL row-level
security policies see it. `is_local` scopes the values to the transaction, so
pooled connections never leak context between requests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(s.database_url, pool_pre_ping=True, pool_size=s.db_pool_size, max_overflow=s.db_max_overflow, pool_timeout=s.db_pool_timeout)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, autoflush=False)
    return _engine


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine, _sessionmaker = None, None


@dataclass(frozen=True, slots=True)
class DbContext:
    org_id: UUID | None = None
    user_id: UUID | None = None
    platform_admin: bool = False


async def apply_context(session: AsyncSession, ctx: DbContext) -> None:
    """Write tenant context into the current transaction for RLS policies."""
    await session.execute(
        text("SELECT set_config('app.org_id', :org, true), set_config('app.user_id', :user, true), set_config('app.platform_admin', :admin, true)"),
        {"org": str(ctx.org_id) if ctx.org_id else "", "user": str(ctx.user_id) if ctx.user_id else "", "admin": "on" if ctx.platform_admin else "off"},
    )


@asynccontextmanager
async def independent_tx() -> AsyncIterator[AsyncSession]:
    """A separate transaction that commits even if the request's transaction rolls back.
    Used for security bookkeeping (failed-login counters, token-reuse revocation)."""
    async with sessionmaker()() as session:
        async with session.begin():
            yield session


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one transaction per request, committed on success."""
    async with sessionmaker()() as session:
        async with session.begin():
            yield session


async def assert_safe_db_role(engine: AsyncEngine) -> None:
    """Refuse to run if the app role could bypass RLS (superuser / BYPASSRLS / table owner)."""
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT r.rolsuper, r.rolbypassrls, "
                    "EXISTS (SELECT 1 FROM pg_tables t WHERE t.schemaname='public' AND t.tableowner = current_user) "
                    "FROM pg_roles r WHERE r.rolname = current_user"
                )
            )
        ).one()
    if any(row):
        raise RuntimeError(
            "Database role used by the API can bypass row-level security (superuser, BYPASSRLS or table owner). Connect as the non-owner application role."
        )
