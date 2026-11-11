"""Shared async Redis client (key-lookup cache now; rate limits + arq broker later)."""
from __future__ import annotations

from redis.asyncio import Redis

from .config import settings

_redis: Redis | None = None


def get_redis() -> Redis:
    """Process-wide Redis client (decoded str responses)."""
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
