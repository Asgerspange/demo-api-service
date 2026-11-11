"""Stage 08 §8.3 — /metrics exposition + admin ingest-job visibility."""
import pytest

from app.storage.repos import JobRepo, UserRepo

pytestmark = pytest.mark.e2e


async def test_metrics_endpoint_exposes_prometheus(api):
    # generate some traffic so the request counter is populated
    await api.get("/healthz")
    r = await api.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    body = r.text
    # core series are present
    for name in ("http_requests_total", "http_request_duration_seconds",
                 "ingest_queue_depth", "ingest_jobs_by_status", "rate_limited_total"):
        assert name in body


async def test_metrics_reflects_job_status_counts(api, db):
    uid = await UserRepo(db).create("m@x.com")
    jobs = JobRepo(db)
    await jobs.create("j-ready", "url", "u", user_id=uid, status="queued")
    await jobs.update("j-ready", status="ready")
    await jobs.create("j-fail", "url", "u2", user_id=uid, status="failed")

    r = await api.get("/metrics")
    body = r.text
    assert 'ingest_jobs_by_status{status="ready"} 1.0' in body
    assert 'ingest_jobs_by_status{status="failed"} 1.0' in body


async def test_admin_jobs_visibility(api, admin_headers, db):
    uid = await UserRepo(db).create("j@x.com")
    jobs = JobRepo(db)
    await jobs.create("job-a", "url", "https://x/y.dem", user_id=uid, status="queued")
    await jobs.update("job-a", status="failed", error="boom")

    r = await api.get("/admin/jobs", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["counts"].get("failed") == 1
    assert any(j["id"] == "job-a" and j["error"] == "boom" for j in body["jobs"])

    # filterable
    failed = await api.get("/admin/jobs?status=failed", headers=admin_headers)
    assert all(j["status"] == "failed" for j in failed.json()["jobs"])

    # admin-gated
    assert (await api.get("/admin/jobs")).status_code == 401
