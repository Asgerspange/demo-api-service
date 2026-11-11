"""Phase 04 — RateLimiter fixed-window logic + scope key mapping (fake Redis, no app)."""
import pytest

from app.auth.context import AuthContext
from app.ratelimit import RateLimiter, scope_redis_key


@pytest.mark.unit
def test_scope_key_client():
    ctx = AuthContext(key_id=7, user_id=1, kind="client", rate_per_hour=100)
    assert scope_redis_key(ctx) == "rl:ck:7"


@pytest.mark.unit
def test_scope_key_server_includes_end_user():
    ctx = AuthContext(key_id=7, user_id=1, kind="server", rate_per_hour=5, end_user="u9")
    assert scope_redis_key(ctx) == "rl:su:7:u9"


@pytest.mark.unit
async def test_hit_allows_up_to_limit_then_blocks(fake_redis):
    rl = RateLimiter(fake_redis, window=3600)
    results = [await rl.hit("rl:ck:1", 3) for _ in range(4)]
    assert [r.allowed for r in results] == [True, True, True, False]
    assert [r.remaining for r in results] == [2, 1, 0, 0]
    assert all(r.limit == 3 for r in results)
    assert results[-1].retry_after > 0 and results[-1].reset > 0
    assert results[0].retry_after == 0


@pytest.mark.unit
async def test_hit_scopes_are_independent(fake_redis):
    rl = RateLimiter(fake_redis, window=3600)
    assert (await rl.hit("rl:a", 1)).allowed is True
    assert (await rl.hit("rl:a", 1)).allowed is False   # second hit on a → blocked
    assert (await rl.hit("rl:b", 1)).allowed is True     # b has its own bucket


@pytest.mark.unit
async def test_reset_is_aligned_to_window(fake_redis):
    rl = RateLimiter(fake_redis, window=3600)
    res = await rl.hit("rl:ck:1", 10)
    assert res.reset % 3600 == 0  # time-aligned window boundary
