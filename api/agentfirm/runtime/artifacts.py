"""Artifact storage. Keys are always `org/{org_id}/executions/{execution_id}/{name}` so a
bucket policy or a bug can never mix organisations. Downloads use presigned URLs (R2)."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Protocol
from uuid import UUID

from agentfirm.core.config import get_settings

SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def object_key(org_id: UUID, execution_id: UUID, name: str) -> str:
    clean = SAFE.sub("-", name).strip("-.")[:180] or "artifact"
    return f"org/{org_id}/executions/{execution_id}/{clean}"


class ArtifactStore(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...


class LocalStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if not p.is_relative_to(self.root):
            raise ValueError("invalid artifact key")
        return p

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(p.write_bytes, data)

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._path(key).read_bytes)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, True)


class R2Store:  # pragma: no cover - requires Cloudflare credentials
    """Cloudflare R2 through its S3-compatible API (boto3 is imported lazily)."""

    def __init__(self) -> None:
        import boto3  # type: ignore[import-not-found]

        s = get_settings()
        self.bucket = s.r2_bucket
        self.client = boto3.client(
            "s3", endpoint_url=s.r2_endpoint, aws_access_key_id=s.r2_access_key_id, aws_secret_access_key=s.r2_secret_access_key, region_name="auto"
        )

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(self.client.put_object, Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    async def get(self, key: str) -> bytes:
        obj = await asyncio.to_thread(self.client.get_object, Bucket=self.bucket, Key=key)
        return obj["Body"].read()

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)


def get_store() -> ArtifactStore:
    s = get_settings()
    return R2Store() if s.artifact_store == "r2" else LocalStore(s.artifacts_dir)
