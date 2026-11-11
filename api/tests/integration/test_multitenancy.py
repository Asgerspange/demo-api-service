"""Stage 16 — idempotency, tier routing, backpressure, webhook delivery, and DR rebuild.

The arq enqueue is monkeypatched so the intake API runs without a live worker; the webhook
delivery task and DR rebuild are exercised directly against the test DB + a fake store/redis.
"""
import fakeredis.aioredis
import orjson
import pytest

import app.ingest.queue as queue_mod
from app.config import settings
from app.dr import rebuild_from_storage
from app.fairness import LANE_ENTERPRISE, LANE_FREE
from app.storage.object_store import canonical_key, index_key, round_key
from app.storage.repos import (
    DemoRepo,
    IdempotencyRepo,
    JobRepo,
    RoundRepo,
    UserRepo,
    WebhookDeadLetterRepo,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _capture_enqueue(monkeypatch):
    calls: list[dict] = []

    async def _fake(job_id, *, lane=None):
        calls.append({"job_id": job_id, "lane": lane})

    monkeypatch.setattr(queue_mod, "enqueue_ingest", _fake)
    return calls


async def _server_key(api, admin_headers, email="mt@x.com"):
    uid = (await api.post("/admin/users", json={"email": email}, headers=admin_headers)).json()["id"]
    key = (await api.post(f"/admin/users/{uid}/keys", json={"kind": "server"},
                          headers=admin_headers)).json()["key"]
    return uid, key


def _sh(key):
    return {"X-Server-Key": key, "X-End-User": "backend-1"}


# --- idempotency (§16.2) ---------------------------------------------------------------

async def test_idempotency_key_returns_same_job_once(api, admin_headers, db, _capture_enqueue):
    _, key = await _server_key(api, admin_headers)
    body = {"source": {"type": "url", "ref": "https://example.com/d.dem"}}
    headers = {**_sh(key), "Idempotency-Key": "abc-123"}

    first = await api.post("/ingest", headers=headers, json=body)
    second = await api.post("/ingest", headers=headers, json=body)

    assert first.status_code == 202
    assert second.json()["job_id"] == first.json()["job_id"]
    assert second.json()["idempotent"] is True
    # only ONE job was actually enqueued (the retry did not create a second parse)
    assert len(_capture_enqueue) == 1
    counts = await JobRepo(db).counts_by_status()
    assert counts.get("queued") == 1


async def test_idempotency_scoped_per_tenant(api, admin_headers, db, _capture_enqueue):
    _, key_a = await _server_key(api, admin_headers, "ta@x.com")
    _, key_b = await _server_key(api, admin_headers, "tb@x.com")
    body = {"source": {"type": "url", "ref": "https://example.com/d.dem"}}
    h = lambda k: {**_sh(k), "Idempotency-Key": "shared"}

    a = await api.post("/ingest", headers=h(key_a), json=body)
    b = await api.post("/ingest", headers=h(key_b), json=body)
    # same key string, different tenants → distinct jobs (no cross-tenant collision)
    assert a.json()["job_id"] != b.json()["job_id"]


# --- tier routing (§16.1) --------------------------------------------------------------

async def test_ingest_routes_to_tier_lane(api, admin_headers, db, _capture_enqueue):
    uid, key = await _server_key(api, admin_headers, "ent@x.com")
    patched = await api.patch(f"/admin/users/{uid}", headers=admin_headers,
                              json={"tier": "enterprise"})
    assert patched.status_code == 200
    r = await api.post("/ingest", headers=_sh(key),
                       json={"source": {"type": "url", "ref": "https://example.com/d.dem"}})
    assert r.json()["lane"] == LANE_ENTERPRISE
    assert _capture_enqueue[-1]["lane"] == LANE_ENTERPRISE


async def test_default_tier_is_standard_not_enterprise(api, admin_headers, db, _capture_enqueue):
    _, key = await _server_key(api, admin_headers, "std@x.com")
    r = await api.post("/ingest", headers=_sh(key),
                       json={"source": {"type": "url", "ref": "https://example.com/d.dem"}})
    assert r.json()["lane"] != LANE_ENTERPRISE and r.json()["lane"] != LANE_FREE


# --- backpressure (§16.1) --------------------------------------------------------------

async def test_backpressure_sheds_above_ceiling(api, admin_headers, db, _capture_enqueue, monkeypatch):
    _, key = await _server_key(api, admin_headers, "bp@x.com")
    monkeypatch.setattr(settings, "ingest_queue_depth_ceiling", 1)

    # Force the measured depth above the ceiling.
    import app.ingest.router as router_mod

    async def _deep(redis, *lanes):
        return 5

    monkeypatch.setattr(router_mod, "queue_depth", _deep)
    r = await api.post("/ingest", headers=_sh(key),
                       json={"source": {"type": "url", "ref": "https://example.com/d.dem"}})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    assert _capture_enqueue == []   # nothing enqueued when shedding


# --- webhook delivery → dead-letter (§16.2) --------------------------------------------

async def test_webhook_delivery_dead_letters_after_budget(db):
    from app.webhook_delivery import webhook_delivery_task

    delivery = {"url": "https://hook.example/x", "payload": {"event": "demo.ready"},
                "secret": "s", "user_id": None, "job_id": None}

    async def _always_500(url, payload, secret, **kw):
        return 500

    import app.webhook_delivery as wd
    # Monkeypatch the signed POST to always fail, and run on the final attempt → dead-letter.
    orig = wd._post_signed
    wd._post_signed = _always_500
    try:
        ctx = {"pool": db, "job_try": settings_max()}  # final attempt → no more retries
        result = await webhook_delivery_task(ctx, delivery)
    finally:
        wd._post_signed = orig

    assert result == "dead_lettered"
    assert await WebhookDeadLetterRepo(db).count() == 1


def settings_max():
    from app.webhooks import MAX_DELIVERY_ATTEMPTS
    return MAX_DELIVERY_ATTEMPTS


async def test_webhook_delivery_retries_before_budget(db):
    from arq.worker import Retry

    from app.webhook_delivery import webhook_delivery_task
    import app.webhook_delivery as wd

    async def _fail(url, payload, secret, **kw):
        return 503

    orig = wd._post_signed
    wd._post_signed = _fail
    try:
        with pytest.raises(Retry):
            await webhook_delivery_task({"pool": db, "job_try": 1},
                                        {"url": "https://h/x", "payload": {}, "secret": ""})
    finally:
        wd._post_signed = orig
    assert await WebhookDeadLetterRepo(db).count() == 0  # not dead-lettered yet


async def test_webhook_delivery_success(db):
    from app.webhook_delivery import webhook_delivery_task
    import app.webhook_delivery as wd

    async def _ok(url, payload, secret, **kw):
        return 200

    orig = wd._post_signed
    wd._post_signed = _ok
    try:
        result = await webhook_delivery_task({"pool": db, "job_try": 1},
                                             {"url": "https://h/x", "payload": {}, "secret": ""})
    finally:
        wd._post_signed = orig
    assert result == "delivered"


# --- DR rebuild from storage (§16.3) ---------------------------------------------------

class FakeStore:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    async def put(self, key, data, **kw):
        self.objects[key] = bytes(data)
        return key

    async def get(self, key):
        return self.objects[key]

    async def list_keys(self, prefix=""):
        return list(self.objects.keys())


async def test_rebuild_from_storage_rederives_mapping(db):
    owner = await UserRepo(db).create("dr@x.com")
    store = FakeStore()
    pv = settings.payload_version
    demo_id = 4242
    rounds = [{"round_index": 1, "key": round_key(demo_id, pv, 1), "byte_size": 100,
               "meta": {"winner": "ct"}},
              {"round_index": 2, "key": round_key(demo_id, pv, 2), "byte_size": 120,
               "meta": {"winner": "t"}}]
    index = {"payload_version": pv, "demo_id": demo_id, "map": "de_nuke", "rounds": rounds}
    store.objects[index_key(demo_id, pv)] = orjson.dumps(index)
    for r in rounds:
        store.objects[r["key"]] = b"x"

    summary = await rebuild_from_storage(db, store, owner_user_id=owner)
    assert summary == {"indexes_found": 1, "demos_rebuilt": 1, "rounds_rebuilt": 2}

    demo = await DemoRepo(db).get(demo_id)
    assert demo is not None and demo["status"] == "ready" and demo["map"] == "de_nuke"
    assert demo["meta"]["rebuilt_from_storage"] is True
    assert demo["storage_key"] == canonical_key(demo_id)
    got = await RoundRepo(db).list_for_demo(demo_id)
    assert [r["round_index"] for r in got] == [1, 2]

    # idempotent — a second run doesn't duplicate
    again = await rebuild_from_storage(db, store, owner_user_id=owner)
    assert again["demos_rebuilt"] == 1


class _FakeArqRedis:
    """fakeredis for the counters + a recorded enqueue_job (the arq pool the worker uses)."""

    def __init__(self, fr):
        self.fr = fr
        self.enqueued: list[tuple] = []

    async def incr(self, k):
        return await self.fr.incr(k)

    async def decr(self, k):
        return await self.fr.decr(k)

    async def expire(self, k, t):
        return await self.fr.expire(k, t)

    async def get(self, k):
        return await self.fr.get(k)

    async def set(self, k, v):
        return await self.fr.set(k, v)

    async def enqueue_job(self, *a, **kw):
        self.enqueued.append((a, kw))


async def test_worker_defers_jobs_for_an_at_capacity_tenant(db, monkeypatch):
    """§16.1 measured: with the per-tenant cap at 1, a tenant's second concurrent job is *deferred*
    (re-enqueued, worker freed) instead of running — so a 500-demo tenant can't monopolize workers
    and stall another tenant. A different tenant's job still runs immediately."""
    from app.fairness import acquire_slot
    from app.ingest import pipeline as pl

    ran: list[str] = []

    async def _fake_run_pipeline(**kw):
        ran.append(kw["job_id"])

    monkeypatch.setattr(pl, "run_pipeline", _fake_run_pipeline)
    monkeypatch.setattr(settings, "ingest_tenant_max_inflight", 1)

    bulk = await UserRepo(db).create("bulk@x.com")
    solo = await UserRepo(db).create("solo@x.com")
    jb1 = await JobRepo(db).create("aaaaaaaa-0000-0000-0000-000000000001", "url", "u", user_id=bulk)
    jb2 = await JobRepo(db).create("aaaaaaaa-0000-0000-0000-000000000002", "url", "u", user_id=bulk)
    js1 = await JobRepo(db).create("bbbbbbbb-0000-0000-0000-000000000001", "url", "u", user_id=solo)

    fr = fakeredis.aioredis.FakeRedis(decode_responses=True)
    arq = _FakeArqRedis(fr)
    ctx = {"pool": db, "store": None, "archive": None, "redis": arq, "queue_name": "arq:queue"}

    # Simulate the bulk tenant already holding its one slot (a parse in flight).
    assert await acquire_slot(arq, bulk, 1) is True

    await pl.ingest_demo(ctx, jb2)     # bulk at cap → deferred, does NOT run
    await pl.ingest_demo(ctx, js1)     # different tenant → runs immediately
    assert ran == [js1]
    # the bulk tenant's second job was re-enqueued with the configured defer
    assert arq.enqueued, "expected a deferred re-enqueue for the at-capacity tenant"
    assert arq.enqueued[-1][1].get("_defer_by") == settings.ingest_defer_seconds


async def test_idempotency_repo_race_returns_first_writer(db):
    uid = await UserRepo(db).create("race@x.com")
    # Two job rows; both try to claim the same key — the first writer wins.
    j1 = await JobRepo(db).create("11111111-1111-1111-1111-111111111111", "url", "u", user_id=uid)
    j2 = await JobRepo(db).create("22222222-2222-2222-2222-222222222222", "url", "u", user_id=uid)
    idem = IdempotencyRepo(db)
    assert await idem.put(uid, "k", j1) == j1
    assert await idem.put(uid, "k", j2) == j1   # second loses, gets the first job_id
