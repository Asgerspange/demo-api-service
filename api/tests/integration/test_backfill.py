"""Stage 14 — backfill: cheap re-derive from parquet, verify-before-flip, GC old version, resumable."""
import hashlib
import os

import pandas as pd
import pytest

from app.backfill import gc_version, run_backfill
from app.ingest.canonical import frames_to_zip
from app.ingest.rounds import Frames, build_round_records
from app.payload import encode_round
from app.storage.object_store import canonical_key, index_key, round_key
from app.storage.repos import BackfillRepo, DemoRepo, RoundRepo, UserRepo

pytestmark = pytest.mark.integration


class FakeStore:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    async def get(self, key):
        return self.objects[key]

    async def put(self, key, data, **kw):
        self.objects[key] = bytes(data); return key

    async def delete(self, key):
        self.objects.pop(key, None)


def _player_row(tick, sid, name, side):
    return dict(tick=tick, round_num=1, steamid=sid, name=name, side=side, team_clan_name="T",
                X=100.0, Y=200.0, Z=64.0, yaw=90.0, pitch=0.0, health=100, armor_value=100,
                balance=800, flash_duration=0.0, has_defuser=False, has_helmet=True,
                is_walking=False, active_weapon_name="ak47", inventory=["AK-47"],
                kills_total=0, deaths_total=0, assists_total=0)


def _frames() -> Frames:
    ticks = [_player_row(t, s, n, sd) for t in range(100, 161, 10)
             for s, n, sd in (("111", "p1", "t"), ("222", "p2", "ct"))]
    rounds = pd.DataFrame([dict(round_num=1, start=100, end=160, official_end=160,
                               winner="t", reason="ct_killed")])
    empty = pd.DataFrame()
    return Frames(ticks=pd.DataFrame(ticks), rounds=rounds, kills=empty, shots=empty,
                  grenades=empty, smokes=empty, infernos=empty,
                  bomb_pickup=empty, bomb_dropped=empty, bomb_planted=empty)


async def _seed_v1(db, store, archive, *, round_count_override=None):
    frames = _frames()
    records = build_round_records(frames)
    uid = await UserRepo(db).create(f"bf{os.urandom(4).hex()}@x.com")
    sha = hashlib.sha256(os.urandom(16)).hexdigest()
    demo_id = await DemoRepo(db).create(uid, sha, "de_inferno", "d", status="queued", payload_version=1)
    archive.objects[canonical_key(demo_id)] = frames_to_zip(frames)   # warm canonical (cold zone)
    for rec in records:
        blob = encode_round(rec.record)
        key = round_key(demo_id, 1, rec.round_index)
        store.objects[key] = blob
        await RoundRepo(db).upsert(demo_id, rec.round_index, key, len(blob), rec.light_meta)
    store.objects[index_key(demo_id, 1)] = b"{}"
    rc = round_count_override if round_count_override is not None else len(records)
    await DemoRepo(db).set_ready(demo_id, round_count=rc, duration_ticks=10,
                                 storage_key=canonical_key(demo_id), meta={})
    return demo_id, [r.round_index for r in records]


async def test_cheap_backfill_flips_version_keeps_old_for_grace(db):
    store, archive = FakeStore(), FakeStore()
    demo_id, idxs = await _seed_v1(db, store, archive)
    run_id = await BackfillRepo(db).create_run(2, "cheap", [demo_id])

    counts = await run_backfill(db, run_id, store=store, archive=archive, target_pv=2, mode="cheap")
    assert counts == {"done": 1}

    # version flipped, v2 written ALONGSIDE v1 (v1 kept for the grace window, §14.2)
    assert (await DemoRepo(db).get(demo_id))["payload_version"] == 2
    for i in idxs:
        assert round_key(demo_id, 2, i) in store.objects
        assert round_key(demo_id, 1, i) in store.objects        # old version still serving
    assert index_key(demo_id, 2) in store.objects and index_key(demo_id, 1) in store.objects
    # demo_rounds now point at the v2 keys
    assert "/v2/" in (await RoundRepo(db).get(demo_id, idxs[0]))["storage_key"]
    assert await BackfillRepo(db).state(run_id, demo_id) == "done"

    # after the grace window, the GC sweep reclaims the old version (v1 gone, v2 intact)
    removed = await gc_version(db, demo_id, 1, store=store)
    assert removed == len(idxs) + 1
    for i in idxs:
        assert round_key(demo_id, 1, i) not in store.objects
        assert round_key(demo_id, 2, i) in store.objects
    assert index_key(demo_id, 1) not in store.objects


async def test_failed_verification_does_not_replace_live_version(db):
    store, archive = FakeStore(), FakeStore()
    # claim 99 rounds but the canonical only yields 1 → verify fails → no flip, no v2
    demo_id, idxs = await _seed_v1(db, store, archive, round_count_override=99)
    run_id = await BackfillRepo(db).create_run(2, "cheap", [demo_id])

    counts = await run_backfill(db, run_id, store=store, archive=archive, target_pv=2, mode="cheap")
    assert counts == {"failed": 1}

    assert (await DemoRepo(db).get(demo_id))["payload_version"] == 1   # untouched
    assert round_key(demo_id, 1, idxs[0]) in store.objects             # live v1 intact
    assert round_key(demo_id, 2, idxs[0]) not in store.objects         # nothing written
    fail = await BackfillRepo(db).failures(run_id)
    assert fail and "count" in fail[0]["error"]


async def test_backfill_is_idempotent_and_resumable(db):
    store, archive = FakeStore(), FakeStore()
    demo_id, idxs = await _seed_v1(db, store, archive)
    run_id = await BackfillRepo(db).create_run(2, "cheap", [demo_id])

    await run_backfill(db, run_id, store=store, archive=archive, target_pv=2, mode="cheap")
    v2_blob = store.objects[round_key(demo_id, 2, idxs[0])]

    # re-running processes nothing new (demo already 'done') and doesn't corrupt v2
    counts = await run_backfill(db, run_id, store=store, archive=archive, target_pv=2, mode="cheap")
    assert counts == {"done": 1}
    assert store.objects[round_key(demo_id, 2, idxs[0])] == v2_blob

    # even a FORCED re-run (state reset to pending; demo already at target) must not GC the new
    # version (old_pv == target → GC skipped)
    await BackfillRepo(db).mark(run_id, demo_id, "pending")
    await run_backfill(db, run_id, store=store, archive=archive, target_pv=2, mode="cheap")
    assert round_key(demo_id, 2, idxs[0]) in store.objects
    assert await BackfillRepo(db).state(run_id, demo_id) == "done"
