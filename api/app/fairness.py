"""Queue fairness, priority lanes & backpressure (Stage 16 §16.1).

The serving path is async + CDN-fronted, but ingestion is a shared, expensive queue. One customer
dumping 500 post-event demos must not delay another customer's single demo. Three mechanisms:

- **Priority lanes** — jobs are routed to a queue by tenant tier (enterprise > standard > free),
  and every live lane outranks the backfill lane. arq workers bind to queues, so the lanes are
  scaled independently (more enterprise workers); see `deploy/README.md`.
- **Per-tenant fairness within a lane** — a Redis-backed cap on *concurrent in-flight parses per
  tenant*. A worker that picks up a job for an at-capacity tenant re-enqueues it with a short defer
  and frees its slot, so a tenant's bulk batch can occupy at most `cap` workers at once and another
  tenant's single job is never stuck behind 500 of theirs.
- **Backpressure** — a queue-depth ceiling at intake: once the lane is too deep, new ingests get
  `429 + Retry-After` instead of growing the queue without bound.

The pure functions here (lane selection, weighted round-robin, backoff) are unit-tested; the Redis
counters are exercised against fakeredis.
"""
from __future__ import annotations

from typing import Iterable, Mapping

# --- priority lanes --------------------------------------------------------------------

# Live ingest queues, highest priority first; the backfill lane is strictly lowest (§16.1).
# `standard` is arq's DEFAULT queue so the baseline single-worker deployment drains the common
# tier with no extra config; enterprise/free/backfill are separate worker pools in production
# (a pool binds a lane via WORKER_QUEUE; see deploy/README.md).
LANE_ENTERPRISE = "arq:queue:enterprise"
LANE_STANDARD = "arq:queue"
LANE_FREE = "arq:queue:free"
LANE_BACKFILL = "arq:queue:backfill"

# Highest → lowest priority. A worker pool consumes one or more lanes; an enterprise pool can
# also drain standard/free when idle (config in deploy/README.md).
LANES_BY_PRIORITY = [LANE_ENTERPRISE, LANE_STANDARD, LANE_FREE, LANE_BACKFILL]

_TIER_LANE = {
    "enterprise": LANE_ENTERPRISE,
    "standard": LANE_STANDARD,
    "free": LANE_FREE,
}


def lane_for_tier(tier: str | None) -> str:
    """Route a tenant's *live* ingest to its tier lane (unknown tier → standard)."""
    return _TIER_LANE.get((tier or "standard").lower(), LANE_STANDARD)


# --- per-tenant concurrency cap --------------------------------------------------------

def _inflight_key(tenant_id: int | str) -> str:
    return f"ingest:inflight:{tenant_id}"


async def acquire_slot(redis, tenant_id: int | str, cap: int, *, ttl: int = 3600) -> bool:
    """Try to take one of a tenant's `cap` concurrent parse slots. Returns False if at capacity.

    Implemented as an atomic INCR with a TTL safety net so a crashed worker that never released its
    slot can't wedge a tenant forever (the counter self-heals after `ttl`). `cap <= 0` means no cap.
    """
    if cap <= 0:
        return True
    key = _inflight_key(tenant_id)
    n = await redis.incr(key)
    if n == 1:
        await redis.expire(key, ttl)
    if n > cap:
        await redis.decr(key)
        return False
    return True


async def release_slot(redis, tenant_id: int | str) -> None:
    """Release a tenant's parse slot (never let the counter go negative)."""
    key = _inflight_key(tenant_id)
    n = await redis.decr(key)
    if n < 0:
        await redis.set(key, 0)


async def inflight(redis, tenant_id: int | str) -> int:
    return int(await redis.get(_inflight_key(tenant_id)) or 0)


# --- backpressure ----------------------------------------------------------------------

async def queue_depth(redis, *lanes: str) -> int:
    """Total queued jobs across the given lanes (arq stores queued ids in a sorted set per queue)."""
    total = 0
    for lane in lanes or tuple(LANES_BY_PRIORITY):
        try:
            total += int(await redis.zcard(lane))
        except Exception:  # noqa: BLE001 — a transient Redis error must not 500 the intake
            pass
    return total


def over_capacity(depth: int, ceiling: int) -> bool:
    """True if a new job should be shed (ceiling <= 0 disables backpressure)."""
    return ceiling > 0 and depth >= ceiling


# --- fairness scheduling (pure, documented + tested) -----------------------------------

def weighted_round_robin(pending_by_tenant: Mapping[str, int],
                         weights: Mapping[str, int] | None = None) -> list[str]:
    """Order a batch of pending jobs so no tenant monopolizes a lane (interleaved round-robin).

    `pending_by_tenant` maps tenant → how many jobs they have queued; `weights` optionally gives a
    tenant more turns per round (e.g. an enterprise tenant). Returns a flat tenant order in which to
    dispatch — round-robin across tenants so a 500-job tenant and a 1-job tenant alternate rather
    than the bulk batch draining first. This is the scheduling intent the per-tenant cap enforces
    at runtime; exposed as a pure function for the fairness test + any future in-process scheduler.
    """
    remaining = {t: n for t, n in pending_by_tenant.items() if n > 0}
    weights = weights or {}
    order: list[str] = []
    while remaining:
        for tenant in list(remaining.keys()):
            take = min(remaining[tenant], max(1, weights.get(tenant, 1)))
            order.extend([tenant] * take)
            remaining[tenant] -= take
            if remaining[tenant] <= 0:
                del remaining[tenant]
    return order


def starvation_factor(order: Iterable[str], tenant: str) -> int:
    """How many jobs run before `tenant`'s FIRST job — the metric the fairness test asserts is
    small even when another tenant floods the queue (a single job shouldn't wait behind 500)."""
    for i, t in enumerate(order):
        if t == tenant:
            return i
    return -1
