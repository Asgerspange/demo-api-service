"""Stage 05 — full pipeline against the real CS2 fixture demo (slow; excluded from PR runs).

This is the golden end-to-end check the acceptance criteria call for: `path` intake of the
real `demo.dem`, a real awpy parse, and the canonical zip + per-round payloads + index.json +
DB rows landing — with bunny storage faked in-memory. Run with `uv run pytest -m slow`.
"""
import hashlib
import os
from pathlib import Path

import pytest

from app.config import settings
from app.ingest.pipeline import run_pipeline
from app.payload import decode_round, validate_round
from app.storage.object_store import canonical_key, index_key, round_key
from app.storage.repos import DemoRepo, JobRepo, RoundRepo, UserRepo

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

# Repo-root demo.dem (de_inferno, 24 rounds) — the Stage 01 smoke fixture.
DEMO_PATH = Path(__file__).resolve().parents[3] / "demo.dem"


class FakeStore:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    async def put(self, key, data, *, content_type="application/octet-stream",
                  cache_control="") -> str:
        self.objects[key] = bytes(data)
        return key


@pytest.mark.skipif(not DEMO_PATH.exists(), reason="demo.dem fixture not present")
async def test_full_ingest_real_demo(db, monkeypatch):
    # The fixture is a 572 MB uncompressed GOTV demo — above the default 500 MB cap; raise it
    # for this test (real ingestion would use a higher cap or compressed transport).
    monkeypatch.setattr(settings, "max_demo_bytes", 800_000_000)
    uid = await UserRepo(db).create("e2e@x.com")
    job_id = "deadbeef-0000-0000-0000-000000000001"
    await JobRepo(db).create(job_id, "path", str(DEMO_PATH), user_id=uid, status="queued")
    await JobRepo(db).update(job_id, progress={"request": {"name": "inferno e2e", "refs": [
        {"source": "hltv", "external_id": "e2e-1"}]}})

    store, archive = FakeStore(), FakeStore()
    await run_pipeline(pool=db, job_id=job_id, store=store, archive=archive)

    job = await JobRepo(db).get(job_id)
    assert job["status"] == "ready", job.get("error")
    demo_id = job["demo_id"]

    demo = await DemoRepo(db).get(demo_id)
    assert demo["status"] == "ready"
    assert demo["map"] == "de_inferno"
    assert demo["round_count"] > 0
    assert demo["sha256"] == hashlib.sha256(DEMO_PATH.read_bytes()).hexdigest()

    pv = settings.payload_version
    assert canonical_key(demo_id) in archive.objects   # cold zone (with the raw .dem)
    assert index_key(demo_id, pv) in store.objects

    rounds = await RoundRepo(db).list_for_demo(demo_id)
    assert len(rounds) == demo["round_count"]

    # A real round payload decodes and matches the viewer schema.
    first = rounds[0]["round_index"]
    blob = store.objects[round_key(demo_id, pv, first)]
    record = decode_round(blob)
    validate_round(record)
    assert record["ticks"]
