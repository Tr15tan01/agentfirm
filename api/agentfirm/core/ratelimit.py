"""Fixed-window rate limiting. Redis when configured; in-process fallback for dev/tests."""

from __future__ import annotations

import time
from collections import defaultdict

from .config import get_settings
from .errors import TooManyRequests

_local: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))
_redis = None


async def _redis_client():  # pragma: no cover - exercised in deployment
    global _redis
    url = get_settings().redis_url
    if not url:
        return None
    if _redis is None:
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(url)
    return _redis


async def hit(key: str, *, limit: int, window_seconds: int = 60) -> None:
    r = await _redis_client()
    if r is not None:
        bucket = f"rl:{key}:{int(time.time() // window_seconds)}"
        count = await r.incr(bucket)
        if count == 1:
            await r.expire(bucket, window_seconds)
    else:
        n, reset = _local[key]
        now = time.monotonic()
        if now >= reset:
            n, reset = 0, now + window_seconds
        count = n + 1
        _local[key] = (count, reset)
    if count > limit:
        raise TooManyRequests("Too many attempts. Please wait a minute and try again.")


def reset_local() -> None:
    _local.clear()
