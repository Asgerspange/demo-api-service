"""Per-tenant bandwidth accounting + cap (Stage 13 §13.3).

A viral demo on a tiny customer must not run up unbounded egress. We count payload bytes
served per tenant in a Redis fixed window and refuse further payload minting once the cap is
exceeded. The cap *value* is a money decision (default 0 = unlimited); the *enforcement
mechanism* lives here and is exercised on every round fetch.
"""
from __future__ import annotations

import time

from .auth.context import AuthContext
from .config import settings


def scope_key(ctx: AuthContext, bucket: int) -> str:
    """Bandwidth bucket key — per owning user (a tenant), time-windowed."""
    return f"bw:{ctx.user_id}:{bucket}"


async def record_and_check(redis, ctx: AuthContext, nbytes: int) -> dict:
    """Add `nbytes` to the tenant's window total and report whether the cap is now exceeded.

    Returns {used, cap, over}. With cap 0 (unlimited) nothing is refused but usage is still
    tracked (so the dashboard/alerting can see it).
    """
    window = settings.bandwidth_window_seconds
    bucket = int(time.time() // window)
    key = scope_key(ctx, bucket)

    pipe = redis.pipeline()
    pipe.incrby(key, max(0, int(nbytes)))
    pipe.expire(key, window + 60)
    used, _ = await pipe.execute()

    cap = settings.bandwidth_cap_bytes
    return {"used": int(used), "cap": cap, "over": cap > 0 and int(used) > cap}
