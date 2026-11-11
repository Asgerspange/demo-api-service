"""Stage 05/13 — intake API: job creation, status, server-key gate, and the admin-only `path` gate.

`POST /ingest` is a backend (write) operation → requires a **server (secret) key**, not a public
client key. The arq enqueue is monkeypatched so the API surface runs without a live worker/Redis.
"""
import pytest

import app.ingest.queue as queue_mod
from app.storage.repos import JobRepo

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _no_real_enqueue(monkeypatch):
    enqueued: list[str] = []

    async def _fake(job_id: str, *, lane: str | None = None) -> None:
        enqueued.append(job_id)

    monkeypatch.setattr(queue_mod, "enqueue_ingest", _fake)
    return enqueued


async def _server_key(api, admin_headers, email="ing@x.com"):
    uid = (await api.post("/admin/users", json={"email": email},
                          headers=admin_headers)).json()["id"]
    issued = await api.post(f"/admin/users/{uid}/keys",
                            json={"kind": "server"}, headers=admin_headers)
    return uid, issued.json()["key"]


async def _client_key(api, admin_headers, email="cust@x.com"):
    uid = (await api.post("/admin/users", json={"email": email},
                          headers=admin_headers)).json()["id"]
    issued = await api.post(f"/admin/users/{uid}/keys",
                            json={"kind": "client", "allowed_origins": ["*.x.com"]},
                            headers=admin_headers)
    return uid, issued.json()["key"]


def _sh(key):
    return {"X-Server-Key": key, "X-End-User": "backend-1"}


async def test_post_ingest_url_returns_job_id(api, admin_headers, db, _no_real_enqueue):
    _, key = await _server_key(api, admin_headers)
    r = await api.post("/ingest", headers=_sh(key), json={
        "source": {"type": "url", "ref": "https://example.com/demo.dem"},
        "name": "my demo",
        "refs": [{"source": "hltv", "external_id": "2378001"}],
    })
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    assert r.json()["status"] == "queued"
    assert _no_real_enqueue == [job_id]

    job = await JobRepo(db).get(job_id)
    assert job["source_type"] == "url"
    assert job["source_ref"] == "https://example.com/demo.dem"
    assert job["status"] == "queued"
    assert job["progress"]["request"]["refs"][0]["external_id"] == "2378001"


async def test_ingest_rejected_for_client_key(api, admin_headers, _no_real_enqueue):
    # A public client key must NOT be able to enqueue ingestion (write op) — server key only.
    _, ckey = await _client_key(api, admin_headers)
    r = await api.post("/ingest",
                       headers={"Authorization": f"Bearer {ckey}", "Origin": "https://app.x.com"},
                       json={"source": {"type": "url", "ref": "https://example.com/d.dem"}})
    assert r.status_code == 403
    assert _no_real_enqueue == []


async def test_ingest_anonymize_flag_stored(api, admin_headers, db, _no_real_enqueue):
    _, key = await _server_key(api, admin_headers)
    job_id = (await api.post("/ingest", headers=_sh(key), json={
        "source": {"type": "url", "ref": "https://example.com/d.dem"},
        "anonymize": True})).json()["job_id"]
    job = await JobRepo(db).get(job_id)
    assert job["progress"]["request"]["anonymize"] is True


async def test_get_ingest_status(api, admin_headers, _no_real_enqueue):
    _, key = await _server_key(api, admin_headers)
    job_id = (await api.post("/ingest", headers=_sh(key), json={
        "source": {"type": "url", "ref": "https://example.com/d.dem"}})).json()["job_id"]

    s = await api.get(f"/ingest/{job_id}", headers=_sh(key))
    assert s.status_code == 200
    body = s.json()
    assert body["job_id"] == job_id and body["status"] == "queued" and body["demo_id"] is None


async def test_path_intake_refused_without_admin(api, admin_headers, _no_real_enqueue):
    _, key = await _server_key(api, admin_headers)
    r = await api.post("/ingest", headers=_sh(key), json={
        "source": {"type": "path", "ref": "/srv/demos/secret.dem"}})
    assert r.status_code == 403
    assert _no_real_enqueue == []  # nothing enqueued


async def test_path_intake_allowed_for_admin(api, admin_headers, _no_real_enqueue):
    _, key = await _server_key(api, admin_headers)
    # server key authenticates the backend; admin token authorizes the path source.
    r = await api.post("/ingest", headers={**_sh(key), **admin_headers}, json={
        "source": {"type": "path", "ref": "/srv/demos/local.dem"}})
    assert r.status_code == 202
    assert len(_no_real_enqueue) == 1


async def test_ingest_requires_auth(api, _no_real_enqueue):
    r = await api.post("/ingest", json={"source": {"type": "url", "ref": "https://x/y.dem"}})
    assert r.status_code == 401


async def test_get_ingest_cross_tenant_404(api, admin_headers, _no_real_enqueue):
    # owner A creates a job; owner B (different key/user) cannot see it.
    _, key_a = await _server_key(api, admin_headers, "a@x.com")
    job_id = (await api.post("/ingest", headers=_sh(key_a), json={
        "source": {"type": "url", "ref": "https://example.com/a.dem"}})).json()["job_id"]

    _, key_b = await _server_key(api, admin_headers, "b@x.com")
    assert (await api.get(f"/ingest/{job_id}", headers=_sh(key_b))).status_code == 404
