"""Redis rate limiting (Stage 4.1).

A fixed-window counter keyed by the request's limit scope (from the AuthContext):
- client key (direct):       `rl:ck:{key_id}`            → the key's hourly limit (default 100)
- server-key end-user (proxy): `rl:su:{key_id}:{end_user}` → the key's owner-set `rate_per_hour`

The window is time-aligned (`…:{bucket}` where bucket = floor(now/window)) so every key resets
on a clean boundary; the counter is `INCR` + `EXPIRE` (atomic enough — the bucket key only
lives for its window). `X-RateLimit-{Limit,Remaining,Reset}` are set on every response; over
the limit → 429 with `Retry-After`.

A server key with no configured `rate_per_hour` is treated as unlimited (no counting).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Response

from .auth.context import AuthContext
from .auth.dependencies import authenticate
from .config import settings
from .redis import get_redis


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset: int          # epoch seconds when the current window resets
    retry_after: int    # seconds to wait when not allowed (0 if allowed)


def scope_redis_key(ctx: AuthContext) -> str:
    """Map an AuthContext's limit scope to its Redis bucket key prefix."""
    scope = ctx.limit_scope
    if scope[0] == "server_user":
        return f"rl:su:{scope[1]}:{scope[2]}"
    return f"rl:ck:{scope[1]}"


class RateLimiter:
    def __init__(self, redis, *, window: int) -> None:
        self.redis = redis
        self.window = window

    async def hit(self, base_key: str, limit: int) -> RateLimitResult:
        now = time.time()
        bucket = int(now // self.window)
        reset = (bucket + 1) * self.window
        key = f"{base_key}:{bucket}"

        pipe = self.redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, int(reset - now) + 60)  # die shortly after the window ends
        count, _ = await pipe.execute()

        allowed = count <= limit
        return RateLimitResult(
            allowed=allowed,
            limit=limit,
            remaining=max(0, limit - count),
            reset=int(reset),
            retry_after=0 if allowed else int(reset - now) + 1,
        )


def _rate_headers(res: RateLimitResult) -> dict[str, str]:
    return {
        "X-RateLimit-Limit": str(res.limit),
        "X-RateLimit-Remaining": str(res.remaining),
        "X-RateLimit-Reset": str(res.reset),
    }


async def enforce_rate_limit(
    response: Response, ctx: AuthContext = Depends(authenticate)
) -> AuthContext:
    """Auth + rate-limit dependency for protected routes. Runs after `authenticate()`,
    returns the same AuthContext, and annotates the response with X-RateLimit-* headers."""
    limit = ctx.rate_per_hour
    if limit is None:
        if ctx.kind == "client":
            limit = settings.client_default_rate_per_hour  # safety net
        else:
            return ctx  # server key with no configured limit → unlimited

    limiter = RateLimiter(get_redis(), window=settings.rate_limit_window_seconds)
    res = await limiter.hit(scope_redis_key(ctx), limit)
    headers = _rate_headers(res)
    if not res.allowed:
        from .metrics import RATE_LIMITED
        RATE_LIMITED.labels(ctx.kind).inc()
        raise HTTPException(
            429, "rate limit exceeded",
            headers={**headers, "Retry-After": str(res.retry_after)},
        )
    response.headers.update(headers)
    return ctx
