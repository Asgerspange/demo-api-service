"""Phase 01 — health endpoint (no external deps)."""
import pytest


@pytest.mark.e2e
async def test_healthz(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["api_version"] == "v1"
