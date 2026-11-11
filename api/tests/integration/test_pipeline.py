"""Stage 05 — the worker pipeline end-to-end against a real test DB, with the network,
the awpy parse, and bunny storage all stubbed (no real I/O).

Covers: a fresh ingest writing canonical.zip + per-round payloads + index.json + DB rows and
archiving the raw .dem; and sha256 dedup short-circuiting the parse while still attaching refs.
"""
import hashlib
import io
import zipfile
from types import SimpleNamespace

import pandas as pd
import pytest

import app.ingest.pipeline as pipeline
from app.config import settings
from app.ingest.classify import Classification
from app.ingest.pipeline import run_pipeline
from app.ingest.rounds import RoundRecord
from app.storage.object_store import canonical_key, index_key, round_key
from app.storage.repos import (
    CollectionRepo,
    DemoRepo,
    JobRepo,
    RefRepo,
    RoundRepo,
    UserRepo,
)

pytestmark = pytest.mark.integration

DEM_BYTES = b"PBDEMS2\x00" + b"fake-demo-content" * 1000


class FakeStore:
    """In-memory ObjectStore stand-in capturing put()s by key."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    async def put(self, key, data, *, content_type="application/octet-stream",
                  cache_control="") -> str:
        self.objects[key] = bytes(data)
        return key


def _valid_record() -> dict:
    """A minimal record that satisfies app.payload.validate_round."""
    player = {f: v for f, v in {
        "steamid": "111", "name": "p1", "X": 1.0, "Y": 2.0, "yaw": 0.0, "health": 100,
        "armor_value": 100, "balance": 800, "flash_duration": 0.0, "has_defuser": False,
        "has_helmet": True, "is_walking": False, "active_weapon_name": "ak47",
        "team_name": "t", "inventory": ["AK-47"],
    }.items()}
    return {"ticks": {100: {"players": [player], "weapon_fires": [], "bomb": None,
                            "grenades": []}},
            "meta": {"round_index": 1, "winner": "t"}, "smokes": [], "infernos": [], "kills": {}}


@pytest.fixture
def stub_parse(monkeypatch):
    """Replace the awpy parse + frame transform + zip compression with deterministic stubs."""
    monkeypatch.setattr(pipeline, "frames_from_demo",
                        lambda dem: SimpleNamespace(ticks=pd.DataFrame({"tick": [1, 2, 3],
                                                                        "steamid": ["111", "111", "111"]})))
    monkeypatch.setattr(pipeline, "build_round_records",
                        lambda frames: [RoundRecord(1, _valid_record(),
                                                    {"round_index": 1, "winner": "t"})])
    monkeypatch.setattr(pipeline, "frames_to_zip", lambda frames: b"PK\x03\x04canonical")


def _classify_ok(_path):
    return Classification(map_name="de_test", is_gotv=True, demo_type="gotv",
                          demo_version="valve_demo_2", tickrate=64,
                          header={"map_name": "de_test"})


async def _make_job(pool, *, refs=None, webhook=None) -> tuple[str, int]:
    uid = await UserRepo(pool).create("owner@x.com")
    job_id = "11111111-1111-1111-1111-111111111111"
    await JobRepo(pool).create(job_id, "path", "/tmp/x.dem", user_id=uid,
                               status="queued", webhook_url=webhook)
    await JobRepo(pool).update(job_id, progress={"request": {"name": "demo", "refs": refs or []}})
    return job_id, uid


async def test_fresh_ingest_produces_ready_demo(db, stub_parse):
    job_id, uid = await _make_job(db, refs=[{"source": "hltv", "external_id": "999"}])
    store, archive = FakeStore(), FakeStore()

    await run_pipeline(
        pool=db, job_id=job_id, store=store, archive=archive,
        acquire=lambda job: _aval(DEM_BYTES), parse=lambda p: object(),
        classify=_classify_ok,
    )

    job = await JobRepo(db).get(job_id)
    assert job["status"] == "ready"
    demo_id = job["demo_id"]
    assert demo_id is not None

    demo = await DemoRepo(db).get(demo_id)
    assert demo["status"] == "ready"
    assert demo["map"] == "de_test"
    assert demo["round_count"] == 1
    assert demo["storage_key"] == canonical_key(demo_id)
    assert demo["raw_storage_key"] == f"{demo_id}/raw.dem.zst"
    assert demo["raw_codec"] == "zstd" and demo["raw_bytes"] > 0
    assert demo["sha256"] == hashlib.sha256(DEM_BYTES).hexdigest()

    # objects written to the right tiers
    pv = settings.payload_version
    assert canonical_key(demo_id) in archive.objects  # canonical.zip in the cold zone, with the raw
    assert index_key(demo_id, pv) in store.objects
    assert round_key(demo_id, pv, 1) in store.objects
    assert f"{demo_id}/raw.dem.zst" in archive.objects

    # per-round DB row + ref attached
    rounds = await RoundRepo(db).list_for_demo(demo_id)
    assert len(rounds) == 1 and rounds[0]["round_index"] == 1
    assert (await RefRepo(db).resolve("hltv", "999", uid))["demo_id"] == demo_id


async def test_dedup_skips_parse_and_attaches_ref(db):
    uid = await UserRepo(db).create("owner@x.com")
    sha = hashlib.sha256(DEM_BYTES).hexdigest()
    existing_id = await DemoRepo(db).create(uid, sha, "de_test", "orig", status="ready",
                                            payload_version=1)

    job_id = "22222222-2222-2222-2222-222222222222"
    await JobRepo(db).create(job_id, "path", "/tmp/x.dem", user_id=uid, status="queued")
    await JobRepo(db).update(job_id, progress={"request": {
        "name": "resubmit", "refs": [{"source": "hltv", "external_id": "555"}]}})

    def _explode(_p):
        raise AssertionError("parse must not run on a dedup hit")

    store, archive = FakeStore(), FakeStore()
    await run_pipeline(pool=db, job_id=job_id, store=store, archive=archive,
                       acquire=lambda job: _aval(DEM_BYTES), parse=_explode,
                       classify=_classify_ok)

    job = await JobRepo(db).get(job_id)
    assert job["status"] == "ready"
    assert job["demo_id"] == existing_id
    assert job["progress"].get("deduped") is True
    # no new demo, no objects written, ref attached to the existing demo
    assert store.objects == {} and archive.objects == {}
    assert (await RefRepo(db).resolve("hltv", "555", uid))["demo_id"] == existing_id


async def test_dedup_grants_access_to_second_tenant(db):
    """A second tenant that ingests already-known content dedups to the existing demo AND is
    granted access to it — otherwise serving (which reads via demo_access) would 404 for them."""
    demos = DemoRepo(db)
    sha = hashlib.sha256(DEM_BYTES).hexdigest()

    uid_a = await UserRepo(db).create("owner-a@x.com")
    existing_id = await demos.create(uid_a, sha, "de_test", "orig", status="ready",
                                     payload_version=1)

    uid_b = await UserRepo(db).create("owner-b@x.com")
    job_id = "33333333-3333-3333-3333-333333333333"
    await JobRepo(db).create(job_id, "path", "/tmp/x.dem", user_id=uid_b, status="queued")
    await JobRepo(db).update(job_id, progress={"request": {"name": "b-resubmit", "refs": []}})

    store, archive = FakeStore(), FakeStore()
    await run_pipeline(pool=db, job_id=job_id, store=store, archive=archive,
                       acquire=lambda job: _aval(DEM_BYTES),
                       parse=lambda _p: (_ for _ in ()).throw(AssertionError("no parse on dedup")),
                       classify=_classify_ok)

    # Both tenants can now read the shared demo; a third, uninvolved tenant cannot.
    assert (await demos.get_for_user(existing_id, uid_a)) is not None
    assert (await demos.get_for_user(existing_id, uid_b)) is not None
    uid_c = await UserRepo(db).create("owner-c@x.com")
    assert (await demos.get_for_user(existing_id, uid_c)) is None


async def test_ref_can_be_shared_across_demos(db, stub_parse):
    # Stage 18: a ref (e.g. an HLTV match id) MAY map to several demos (one per map). Attaching the
    # same ref to a freshly-ingested demo B keeps it on demo A too — both resolve.
    job_id, uid = await _make_job(db, refs=[{"source": "hltv", "external_id": "777"}])
    demo_a = await DemoRepo(db).create(uid, "a" * 64, "de_test", "A", status="ready")
    await RefRepo(db).add(demo_a, "hltv", "777", uid)
    store, archive = FakeStore(), FakeStore()
    await run_pipeline(pool=db, job_id=job_id, store=store, archive=archive,
                       acquire=lambda job: _aval(DEM_BYTES), parse=lambda p: object(),
                       classify=_classify_ok)

    job = await JobRepo(db).get(job_id)
    new_demo_id = job["demo_id"]
    assert new_demo_id != demo_a
    # both demos now carry the shared ref (one-to-many resolution)
    bound = {r["demo_id"] for r in await RefRepo(db).resolve_all("hltv", "777", uid)}
    assert bound == {demo_a, new_demo_id}


async def test_unsupported_demo_marks_job_failed(db, stub_parse):
    job_id, _ = await _make_job(db)

    def _reject(_p):
        from app.ingest.errors import UnsupportedDemoError
        raise UnsupportedDemoError("CSGO/source1 demos are not supported (CS2 only)")

    store, archive = FakeStore(), FakeStore()
    await run_pipeline(pool=db, job_id=job_id, store=store, archive=archive,
                       acquire=lambda job: _aval(DEM_BYTES), parse=lambda p: object(),
                       classify=_reject)

    job = await JobRepo(db).get(job_id)
    assert job["status"] == "failed"
    assert "CS2" in job["error"]


async def test_parse_failure_marks_job_failed_cleanly(db):
    """Stage 11 §11.1.8: a corrupt/truncated demo (or the int32 awpy crash) must fail the job
    with a precise error — never crash the worker mid-parse."""
    job_id, _ = await _make_job(db)

    def _boom(_p):
        raise RuntimeError("could not parse tick 0 (truncated demo)")

    store, archive = FakeStore(), FakeStore()
    await run_pipeline(pool=db, job_id=job_id, store=store, archive=archive,
                       acquire=lambda job: _aval(DEM_BYTES), parse=_boom, classify=_classify_ok)

    job = await JobRepo(db).get(job_id)
    assert job["status"] == "failed"
    assert "truncated demo" in job["error"]
    # the demo row created before parse is marked failed too (not left dangling 'parsing')
    demo = await DemoRepo(db).get(job["demo_id"])
    assert demo["status"] == "failed"


async def _aval(value):
    """Wrap a value in an awaitable (acquire hooks are async)."""
    return value


# ── Stage 18: multi-demo archive fan-out ────────────────────────────────────────────────

def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _classify_by_content(_path):
    """Classify the temp .dem by a marker byte so each map in an archive gets a distinct map name."""
    data = open(_path, "rb").read()
    mp = "de_nuke" if b"NUKE" in data[:64] else "de_mirage"
    return Classification(map_name=mp, is_gotv=True, demo_type="gotv",
                          demo_version="valve_demo_2", tickrate=64, header={"map_name": mp})


_DEM_NUKE = b"PBDEMS2\x00NUKE" + b"n" * 2000
_DEM_MIRAGE = b"PBDEMS2\x00MIRG" + b"m" * 2000


async def test_multi_demo_archive_fans_out_into_a_collection(db, stub_parse):
    job_id, uid = await _make_job(db, refs=[{"source": "hltv", "external_id": "2378001"}])
    container = _zip({"de_nuke.dem": _DEM_NUKE, "de_mirage.dem": _DEM_MIRAGE})
    store, archive = FakeStore(), FakeStore()
    await run_pipeline(pool=db, job_id=job_id, store=store, archive=archive,
                       acquire=lambda job: _aval(container), parse=lambda p: object(),
                       classify=_classify_by_content)

    job = await JobRepo(db).get(job_id)
    assert job["status"] == "ready"
    cid = job["progress"]["collection_id"]
    assert cid and len(job["progress"]["demo_ids"]) == 2

    # the collection groups both maps, and carries the match id
    coll = await CollectionRepo(db).resolve(uid, "hltv", "2378001")
    assert coll["id"] == cid
    demos = await DemoRepo(db).list_for_collection(cid)
    assert {d["map"] for d in demos} == {"de_nuke", "de_mirage"}
    assert all(d["status"] == "ready" for d in demos)

    # one HLTV match id resolves to BOTH maps (shared external id, §18.3)
    bound = await RefRepo(db).resolve_all("hltv", "2378001", uid)
    assert len(bound) == 2


async def test_re_ingesting_an_archive_dedups_per_demo_and_reuses_the_collection(db, stub_parse):
    job_id, uid = await _make_job(db, refs=[{"source": "hltv", "external_id": "42"}])
    container = _zip({"de_nuke.dem": _DEM_NUKE, "de_mirage.dem": _DEM_MIRAGE})
    store, archive = FakeStore(), FakeStore()
    await run_pipeline(pool=db, job_id=job_id, store=store, archive=archive,
                       acquire=lambda job: _aval(container), parse=lambda p: object(),
                       classify=_classify_by_content)
    cid = (await JobRepo(db).get(job_id))["progress"]["collection_id"]
    first = {d["id"] for d in await DemoRepo(db).list_for_collection(cid)}

    # re-submit the SAME archive as a new job for the same owner → no new demos, same collection
    job2 = "22222222-2222-2222-2222-222222222222"
    await JobRepo(db).create(job2, "path", "/tmp/x.dem", user_id=uid, status="queued")
    await JobRepo(db).update(job2, progress={"request": {"name": "again",
                             "refs": [{"source": "hltv", "external_id": "42"}]}})
    await run_pipeline(pool=db, job_id=job2, store=FakeStore(), archive=FakeStore(),
                       acquire=lambda job: _aval(container), parse=lambda p: object(),
                       classify=_classify_by_content)

    cid2 = (await JobRepo(db).get(job2))["progress"]["collection_id"]
    assert cid2 == cid                                   # same collection reused
    second = {d["id"] for d in await DemoRepo(db).list_for_collection(cid)}
    assert second == first                               # dedup → no new demos


async def test_archive_with_split_parts_reassembles_one_demo(db, stub_parse):
    job_id, uid = await _make_job(db)
    head = b"PBDEMS2\x00NUKE" + b"head" * 200
    tail = b"taildata" * 200
    container = _zip({"match_p1.dem": head, "match_p2.dem": tail})
    store, archive = FakeStore(), FakeStore()
    await run_pipeline(pool=db, job_id=job_id, store=store, archive=archive,
                       acquire=lambda job: _aval(container), parse=lambda p: object(),
                       classify=_classify_by_content)
    job = await JobRepo(db).get(job_id)
    # parts collapse to ONE demo → single-demo path (no collection)
    assert job["status"] == "ready"
    assert job["progress"].get("collection_id") is None
    demo = await DemoRepo(db).get(job["demo_id"])
    assert demo["status"] == "ready"
