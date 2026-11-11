"""Stage 16 §16.1 — queue fairness, priority lanes & backpressure."""
import fakeredis.aioredis
import pytest

from app.fairness import (
    LANE_BACKFILL,
    LANE_ENTERPRISE,
    LANE_FREE,
    LANE_STANDARD,
    LANES_BY_PRIORITY,
    acquire_slot,
    inflight,
    lane_for_tier,
    over_capacity,
    queue_depth,
    release_slot,
    starvation_factor,
    weighted_round_robin,
)

pytestmark = pytest.mark.unit


def test_lane_for_tier_routes_by_tier():
    assert lane_for_tier("enterprise") == LANE_ENTERPRISE
    assert lane_for_tier("standard") == LANE_STANDARD
    assert lane_for_tier("free") == LANE_FREE
    assert lane_for_tier(None) == LANE_STANDARD       # unknown → standard
    assert lane_for_tier("bogus") == LANE_STANDARD


def test_lane_priority_order_live_above_backfill():
    # enterprise > standard > free > backfill (strictly lowest)
    assert LANES_BY_PRIORITY == [LANE_ENTERPRISE, LANE_STANDARD, LANE_FREE, LANE_BACKFILL]
    assert LANES_BY_PRIORITY[-1] == LANE_BACKFILL


def test_backpressure_ceiling():
    assert over_capacity(100, 100) is True
    assert over_capacity(99, 100) is False
    assert over_capacity(10_000, 0) is False          # 0 disables backpressure


def test_weighted_round_robin_does_not_starve_a_small_tenant():
    # The fairness intent: a 1-job tenant interleaves with a 500-job tenant rather than waiting
    # behind all 500 (§16.1 acceptance, modeled by the scheduler).
    order = weighted_round_robin({"bulk": 500, "solo": 1})
    assert starvation_factor(order, "solo") <= 1       # solo runs essentially immediately
    assert len(order) == 501


def test_weighted_round_robin_respects_weights():
    order = weighted_round_robin({"ent": 4, "free": 4}, weights={"ent": 2})
    # enterprise gets 2 turns per round → its 4 jobs all dispatch within the first 6 slots
    assert order[:3] == ["ent", "ent", "free"]


async def test_acquire_slot_caps_per_tenant():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cap = 2
    assert await acquire_slot(redis, "t1", cap) is True
    assert await acquire_slot(redis, "t1", cap) is True
    assert await acquire_slot(redis, "t1", cap) is False     # at cap → refused
    assert await inflight(redis, "t1") == 2
    # a different tenant is unaffected (fairness: one tenant can't consume another's slots)
    assert await acquire_slot(redis, "t2", cap) is True
    # releasing frees a slot
    await release_slot(redis, "t1")
    assert await acquire_slot(redis, "t1", cap) is True


async def test_acquire_slot_no_cap_always_succeeds():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    for _ in range(10):
        assert await acquire_slot(redis, "t", 0) is True


async def test_release_never_goes_negative():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await release_slot(redis, "t")
    assert await inflight(redis, "t") == 0


async def test_queue_depth_sums_lanes():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await redis.zadd(LANE_ENTERPRISE, {"a": 1, "b": 2})
    await redis.zadd(LANE_STANDARD, {"c": 1})
    assert await queue_depth(redis, LANE_ENTERPRISE, LANE_STANDARD) == 3
