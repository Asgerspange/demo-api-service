"""Phase 02 — repository CRUD against the real test MySQL (bunny not involved here)."""
import uuid

import pymysql
import pytest

from app.storage.repos import (
    DemoRepo,
    JobRepo,
    KeyRepo,
    RefRepo,
    RoundRepo,
    UserRepo,
)

pytestmark = pytest.mark.integration


async def _make_user(pool, email="owner@example.com") -> int:
    return await UserRepo(pool).create(email, display_name="Owner")


async def _make_demo(pool, user_id, sha256="a" * 64) -> int:
    return await DemoRepo(pool).create(
        owner_user_id=user_id, sha256=sha256, map="de_mirage", name="match.dem"
    )


async def test_user_crud(db):
    users = UserRepo(db)
    uid = await users.create("a@b.com", display_name="Alice")
    got = await users.get(uid)
    assert got["email"] == "a@b.com" and got["status"] == "active"
    assert (await users.get_by_email("a@b.com"))["id"] == uid


async def test_key_create_lookup_and_revoke(db):
    uid = await _make_user(db)
    keys = KeyRepo(db)
    kid = await keys.create(
        user_id=uid, kind="client", prefix="pk_live", key_hash="h" * 64,
        last4="ab12", allowed_origins=["https://*.site.com"], rate_per_hour=100,
    )
    found = await keys.get_by_hash("h" * 64)
    assert found["id"] == kid
    assert found["allowed_origins"] == ["https://*.site.com"]  # JSON decoded

    await keys.revoke(kid)
    assert await keys.get_by_hash("h" * 64) is None  # only active keys returned


async def test_demo_lifecycle_and_sha_dedup(db):
    uid = await _make_user(db)
    demos = DemoRepo(db)
    did = await _make_demo(db, uid, sha256="b" * 64)

    demo = await demos.get(did)
    assert demo["status"] == "queued" and demo["payload_version"] == 1

    await demos.update_status(did, "parsing")
    assert (await demos.get(did))["status"] == "parsing"

    await demos.set_ready(
        did, round_count=24, duration_ticks=120000,
        storage_key="7/canonical.zip", meta={"map_name": "de_mirage"},
    )
    ready = await demos.get(did)
    assert ready["status"] == "ready"
    assert ready["round_count"] == 24
    assert ready["meta"] == {"map_name": "de_mirage"}
    assert ready["ready_at"] is not None

    assert (await demos.get_by_sha256("b" * 64))["id"] == did

    # sha256 UNIQUE → idempotent ingestion; a second insert with the same hash fails.
    with pytest.raises(pymysql.err.IntegrityError):
        await _make_demo(db, uid, sha256="b" * 64)


async def test_round_upsert_and_list(db):
    uid = await _make_user(db)
    did = await _make_demo(db, uid)
    rounds = RoundRepo(db)
    await rounds.upsert(did, 0, "7/v1/round-0.bin", 1234, {"winner": "ct"})
    await rounds.upsert(did, 1, "7/v1/round-1.bin", 2345, {"winner": "t"})
    # upsert is idempotent on (demo_id, round_index): update, not duplicate.
    await rounds.upsert(did, 0, "7/v1/round-0.bin", 9999, {"winner": "ct"})

    listed = await rounds.list_for_demo(did)
    assert [r["round_index"] for r in listed] == [0, 1]
    assert (await rounds.get(did, 0))["byte_size"] == 9999
    assert (await rounds.get(did, 0))["meta"] == {"winner": "ct"}


async def test_rounds_cascade_delete_with_demo(db):
    uid = await _make_user(db)
    did = await _make_demo(db, uid)
    await RoundRepo(db).upsert(did, 0, "k", 1, {"x": 1})
    async with db.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM demos WHERE id = %s", (did,))
        await conn.commit()
    assert await RoundRepo(db).list_for_demo(did) == []


async def test_external_refs_resolve_and_dedupe(db):
    uid = await _make_user(db)
    did = await _make_demo(db, uid)
    refs = RefRepo(db)
    await refs.add(did, "hltv", "2380000", uid)
    await refs.add(did, "faceit", "abc-123", uid)
    await refs.add(did, "hltv", "2380000", uid)  # idempotent re-add survives dedup

    assert (await refs.resolve("hltv", "2380000", uid))["demo_id"] == did
    assert await refs.resolve("hltv", "9999999", uid) is None
    assert {r["source"] for r in await refs.list_for_demo(did, uid)} == {"hltv", "faceit"}


async def test_job_state_transitions(db):
    jobs = JobRepo(db)
    jid = str(uuid.uuid4())
    await jobs.create(jid, source_type="url", source_ref="https://example.com/x.dem")
    assert (await jobs.get(jid))["status"] == "queued"

    await jobs.update(jid, status="downloading", progress={"pct": 10})
    mid = await jobs.get(jid)
    assert mid["status"] == "downloading" and mid["progress"] == {"pct": 10}

    await jobs.update(jid, status="failed", error="boom")
    done = await jobs.get(jid)
    assert done["status"] == "failed" and done["error"] == "boom"
