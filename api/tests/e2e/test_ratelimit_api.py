"""Phase 04 — rate limiting end-to-end through the ASGI app (GET /v1/whoami)."""
import pytest

pytestmark = pytest.mark.e2e


async def _issue(api, admin_headers, kind, email, **body):
    uid = (await api.post("/admin/users", json={"email": email},
                          headers=admin_headers)).json()["id"]
    issued = await api.post(f"/admin/users/{uid}/keys",
                            json={"kind": kind, **body}, headers=admin_headers)
    return uid, issued.json()


async def test_client_key_429_after_limit_with_retry_after(api, admin_headers):
    _, key = await _issue(api, admin_headers, "client", "rl@x.com",
                          allowed_origins=["*.x.com"], rate_per_hour=3)
    h = {"Authorization": f"Bearer {key['key']}", "Origin": "https://app.x.com"}
    codes = [(await api.get("/v1/whoami", headers=h)).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]

    blocked = await api.get("/v1/whoami", headers=h)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    assert blocked.headers["X-RateLimit-Limit"] == "3"
    assert blocked.headers["X-RateLimit-Remaining"] == "0"


async def test_ratelimit_headers_on_success(api, admin_headers):
    _, key = await _issue(api, admin_headers, "client", "h@x.com",
                          allowed_origins=["*.x.com"])  # default 100/hr
    h = {"Authorization": f"Bearer {key['key']}", "Origin": "https://app.x.com"}
    r = await api.get("/v1/whoami", headers=h)
    assert r.status_code == 200
    assert r.headers["X-RateLimit-Limit"] == "100"
    assert r.headers["X-RateLimit-Remaining"] == "99"
    assert int(r.headers["X-RateLimit-Reset"]) > 0


async def test_server_key_buckets_isolated_per_end_user(api, admin_headers):
    _, key = await _issue(api, admin_headers, "server", "s@x.com", rate_per_hour=2)
    base = {"X-Server-Key": key["key"]}
    a = {**base, "X-End-User": "alice"}
    b = {**base, "X-End-User": "bob"}

    assert [(await api.get("/v1/whoami", headers=a)).status_code for _ in range(3)] == [200, 200, 429]
    # bob has a separate bucket — unaffected by alice exhausting hers
    assert (await api.get("/v1/whoami", headers=b)).status_code == 200
    assert (await api.get("/v1/whoami", headers=b)).status_code == 200
    assert (await api.get("/v1/whoami", headers=b)).status_code == 429


async def test_server_key_without_configured_limit_is_unlimited(api, admin_headers):
    # No rate_per_hour on a server key → no limiting, no X-RateLimit headers.
    _, key = await _issue(api, admin_headers, "server", "u@x.com")
    h = {"X-Server-Key": key["key"], "X-End-User": "user-1"}
    for _ in range(5):
        r = await api.get("/v1/whoami", headers=h)
        assert r.status_code == 200
    assert "X-RateLimit-Limit" not in r.headers
