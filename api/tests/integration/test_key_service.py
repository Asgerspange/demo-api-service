"""Phase 03 — KeyService: issuance, cached verify, revoke, rotation grace (test MySQL + fake Redis)."""
import pytest

from app.auth.keys import hash_key
from app.auth.service import KeyService
from app.storage.repos import KeyRepo, UserRepo

pytestmark = pytest.mark.integration


def make_svc(db, fake_redis, **kw) -> KeyService:
    opts = dict(cache_ttl=30, rotation_grace=86_400, default_rate=100)
    opts.update(kw)
    return KeyService(KeyRepo(db), fake_redis, **opts)


async def _user(db, email="a@b.com") -> int:
    return await UserRepo(db).create(email)


async def test_issue_client_applies_default_rate_and_origins(db, fake_redis):
    uid = await _user(db)
    svc = make_svc(db, fake_redis)
    kid, gen = await svc.issue(uid, "client", allowed_origins=["*.x.com"])
    rec = await svc.verify(gen.key_hash)
    assert rec["id"] == kid and rec["kind"] == "client"
    assert rec["rate_per_hour"] == 100
    assert rec["allowed_origins"] == ["*.x.com"]


async def test_issue_server_has_no_origins_and_no_default_limit(db, fake_redis):
    uid = await _user(db)
    svc = make_svc(db, fake_redis)
    _, gen = await svc.issue(uid, "server")
    rec = await svc.verify(gen.key_hash)
    assert rec["kind"] == "server"
    assert rec["allowed_origins"] == []
    assert rec["rate_per_hour"] is None


async def test_verify_populates_cache(db, fake_redis):
    uid = await _user(db)
    svc = make_svc(db, fake_redis)
    _, gen = await svc.issue(uid, "client")
    assert await fake_redis.get(f"key:{gen.key_hash}") is None
    await svc.verify(gen.key_hash)
    assert await fake_redis.get(f"key:{gen.key_hash}") is not None


async def test_unknown_key_is_negative_cached(db, fake_redis):
    svc = make_svc(db, fake_redis)
    h = hash_key("pk_live_doesnotexist")
    assert await svc.verify(h) is None
    assert await fake_redis.get(f"key:{h}") == "__miss__"


async def test_revoke_busts_cache_and_invalidates(db, fake_redis):
    uid = await _user(db)
    svc = make_svc(db, fake_redis)
    kid, gen = await svc.issue(uid, "client")
    assert await svc.verify(gen.key_hash) is not None     # cached active
    await svc.revoke(kid)
    assert await svc.verify(gen.key_hash) is None          # immediately invalid


async def test_rotation_keeps_old_key_valid_during_grace(db, fake_redis):
    uid = await _user(db)
    svc = make_svc(db, fake_redis, rotation_grace=3600)
    kid, gen = await svc.issue(uid, "server")
    new_id, new_gen = await svc.rotate(kid)
    assert new_id != kid
    assert await svc.verify(gen.key_hash) is not None      # old still valid in grace
    assert await svc.verify(new_gen.key_hash) is not None  # new valid


async def test_expired_grace_invalidates_old_key(db, fake_redis):
    uid = await _user(db)
    svc = make_svc(db, fake_redis, rotation_grace=3600)
    kid, gen = await svc.issue(uid, "server")
    await svc.rotate(kid)
    # Force the grace window to have already elapsed, then bust the cache.
    async with db.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE api_keys SET expires_at = DATE_SUB(CURRENT_TIMESTAMP, INTERVAL 10 SECOND) "
                "WHERE id = %s", (kid,))
        await conn.commit()
    await fake_redis.flushall()
    assert await svc.verify(gen.key_hash) is None


async def test_set_attrs_updates_and_busts_cache(db, fake_redis):
    uid = await _user(db)
    svc = make_svc(db, fake_redis)
    kid, gen = await svc.issue(uid, "client", allowed_origins=["*.a.com"])
    await svc.verify(gen.key_hash)  # warm the cache
    await svc.set_attrs(kid, allowed_origins=["*.b.com"], rate_per_hour=50)
    rec = await svc.verify(gen.key_hash)
    assert rec["allowed_origins"] == ["*.b.com"]
    assert rec["rate_per_hour"] == 50
