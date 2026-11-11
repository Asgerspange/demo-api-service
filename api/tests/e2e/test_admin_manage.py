"""Phase 03/04 admin management — list a user's keys, rename/suspend users (with auth
enforcement), and live rate-limit usage. Backs the admin dashboard."""
import pytest

pytestmark = pytest.mark.e2e


async def _user(api, admin_headers, email) -> int:
    return (await api.post("/admin/users", json={"email": email},
                           headers=admin_headers)).json()["id"]


async def _issue(api, admin_headers, uid, kind, **body) -> dict:
    return (await api.post(f"/admin/users/{uid}/keys",
                           json={"kind": kind, **body}, headers=admin_headers)).json()


async def test_list_user_keys_is_sanitized(api, admin_headers):
    uid = await _user(api, admin_headers, "lk@x.com")
    await _issue(api, admin_headers, uid, "client", allowed_origins=["*.x.com"])
    await _issue(api, admin_headers, uid, "server")
    r = await api.get(f"/admin/users/{uid}/keys", headers=admin_headers)
    assert r.status_code == 200
    keys = r.json()["keys"]
    assert len(keys) == 2
    assert {k["kind"] for k in keys} == {"client", "server"}
    # never leak the secret hash
    assert all("key_hash" not in k for k in keys)
    assert all({"id", "prefix", "last4", "allowed_origins", "rate_per_hour", "status"} <= k.keys()
               for k in keys)


async def test_list_keys_unknown_user_404(api, admin_headers):
    r = await api.get("/admin/users/99999/keys", headers=admin_headers)
    assert r.status_code == 404


async def test_rename_user(api, admin_headers):
    uid = await _user(api, admin_headers, "rn@x.com")
    r = await api.patch(f"/admin/users/{uid}", json={"display_name": "Renamed"},
                        headers=admin_headers)
    assert r.status_code == 200
    users = (await api.get("/admin/users", headers=admin_headers)).json()["users"]
    assert next(u for u in users if u["id"] == uid)["display_name"] == "Renamed"


async def test_suspend_user_disables_their_keys(api, admin_headers):
    uid = await _user(api, admin_headers, "sus@x.com")
    key = await _issue(api, admin_headers, uid, "client", allowed_origins=["*.x.com"])
    h = {"Authorization": f"Bearer {key['key']}", "Origin": "https://app.x.com"}
    assert (await api.get("/v1/whoami", headers=h)).status_code == 200

    await api.patch(f"/admin/users/{uid}", json={"status": "suspended"}, headers=admin_headers)
    assert (await api.get("/v1/whoami", headers=h)).status_code == 401  # key blocked at once

    await api.patch(f"/admin/users/{uid}", json={"status": "active"}, headers=admin_headers)
    assert (await api.get("/v1/whoami", headers=h)).status_code == 200  # reactivated


async def test_update_unknown_user_404(api, admin_headers):
    r = await api.patch("/admin/users/99999", json={"display_name": "x"}, headers=admin_headers)
    assert r.status_code == 404


async def test_usage_reports_client_key_consumption(api, admin_headers):
    uid = await _user(api, admin_headers, "uc@x.com")
    key = await _issue(api, admin_headers, uid, "client", allowed_origins=["*.x.com"],
                       rate_per_hour=5)
    h = {"Authorization": f"Bearer {key['key']}", "Origin": "https://app.x.com"}
    await api.get("/v1/whoami", headers=h)
    await api.get("/v1/whoami", headers=h)

    usage = (await api.get("/admin/usage", headers=admin_headers)).json()
    assert usage["window_seconds"] == 3600 and usage["reset"] > 0
    entry = next(k for k in usage["keys"] if k["key_id"] == key["id"])
    assert entry["kind"] == "client" and entry["limit"] == 5 and entry["used"] == 2


async def test_usage_breaks_down_server_key_by_end_user(api, admin_headers):
    uid = await _user(api, admin_headers, "us@x.com")
    key = await _issue(api, admin_headers, uid, "server", rate_per_hour=10)
    base = {"X-Server-Key": key["key"]}
    await api.get("/v1/whoami", headers={**base, "X-End-User": "alice"})
    await api.get("/v1/whoami", headers={**base, "X-End-User": "alice"})
    await api.get("/v1/whoami", headers={**base, "X-End-User": "bob"})

    usage = (await api.get("/admin/usage", headers=admin_headers)).json()
    entry = next(k for k in usage["keys"] if k["key_id"] == key["id"])
    assert entry["used"] == 3
    by_user = {e["end_user"]: e["used"] for e in entry["end_users"]}
    assert by_user == {"alice": 2, "bob": 1}


async def test_dashboard_html_is_served(api):
    r = await api.get("/admin/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Demoviewer" in r.text and "Admin" in r.text
