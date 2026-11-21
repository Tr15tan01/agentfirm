"""Publish manifests as immutable agent versions, and roll back by moving `is_current`.

Run by platform operators (owner DB role) — or, from Phase 6, by super-admins through
the admin API. Every publish/rollback writes a platform audit entry.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agentfirm.modules.agents.models import Agent, AgentVersion

from .contracts import AgentManifest
from .registry import registry


class PublishError(Exception):
    pass


@dataclass(frozen=True)
class PublishResult:
    agent: str
    version: str
    status: Literal["created", "unchanged"]


def _semver(v: str) -> tuple[int, int, int]:
    a, b, c = (int(x) for x in v.split("."))
    return a, b, c


def _payload(m: AgentManifest) -> dict:
    return m.model_dump(mode="json") | {"status": "published"}


async def _audit(session: AsyncSession, action: str, target: str, after: dict) -> None:
    await session.execute(
        text("SELECT log_platform_audit(:a, 'agent_version', :t, NULL, 'cli', CAST(:after AS jsonb))"),
        {"a": action, "t": target, "after": json.dumps(after)},
    )


async def publish(session: AsyncSession, manifest: AgentManifest) -> PublishResult:
    agent = (await session.execute(select(Agent).where(Agent.key == manifest.key))).scalar_one_or_none()
    if agent is None:
        agent = Agent(key=manifest.key, name=manifest.name, description=manifest.description)
        session.add(agent)
        await session.flush()

    payload = _payload(manifest)
    existing = (
        await session.execute(select(AgentVersion).where(AgentVersion.agent_id == agent.id, AgentVersion.version == manifest.version))
    ).scalar_one_or_none()
    if existing is not None:
        if existing.manifest == payload:
            return PublishResult(manifest.key, manifest.version, "unchanged")
        raise PublishError(f"{manifest.key} {manifest.version} is already published with different content — bump the version.")

    current = (await session.execute(select(AgentVersion).where(AgentVersion.agent_id == agent.id, AgentVersion.is_current.is_(True)))).scalar_one_or_none()
    if current is not None and _semver(manifest.version) <= _semver(current.version):
        raise PublishError(f"{manifest.key}: new version {manifest.version} must be greater than current {current.version}.")

    await session.execute(update(AgentVersion).where(AgentVersion.agent_id == agent.id).values(is_current=False))
    session.add(AgentVersion(agent_id=agent.id, version=manifest.version, manifest=payload, published_at=datetime.now(UTC), is_current=True))
    agent.name, agent.description = manifest.name, manifest.description
    await session.flush()
    await _audit(session, "agent.version_published", f"{manifest.key}@{manifest.version}", {"previous": current.version if current else None})
    return PublishResult(manifest.key, manifest.version, "created")


async def rollback(session: AsyncSession, key: str, version: str) -> None:
    target = (
        await session.execute(select(AgentVersion).join(Agent, Agent.id == AgentVersion.agent_id).where(Agent.key == key, AgentVersion.version == version))
    ).scalar_one_or_none()
    if target is None:
        raise PublishError(f"{key} {version} not found.")
    await session.execute(update(AgentVersion).where(AgentVersion.agent_id == target.agent_id).values(is_current=False))
    await session.execute(update(AgentVersion).where(AgentVersion.id == target.id).values(is_current=True))
    await _audit(session, "agent.version_rolled_back", f"{key}@{version}", {})


async def publish_all(session: AsyncSession) -> list[PublishResult]:
    return [await publish(session, m) for m in registry().agents.values()]


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Publish agent manifests or roll back a version.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rollback", nargs=2, metavar=("AGENT", "VERSION"))
    args = parser.parse_args()
    engine = create_async_engine(os.environ["AGENTFIRM_MIGRATIONS_DATABASE_URL"])
    async with async_sessionmaker(engine)() as session:
        async with session.begin():
            if args.rollback:
                await rollback(session, *args.rollback)
                print(f"Rolled back {args.rollback[0]} to {args.rollback[1]}")
            else:
                for r in await publish_all(session):
                    print(f"{r.agent:<10} {r.version:<8} {r.status}")
            if args.dry_run:
                await session.rollback()
                print("(dry run — nothing committed)")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
