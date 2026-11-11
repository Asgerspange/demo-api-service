"""Phase 03 — owner-only admin API end-to-end."""
import pytest

pytestmark = pytest.mark.e2e


async def test_admin_requires_token(api):
    r = await api.post("/admin/users", json={"email": "a@b.com"})
    assert r.status_code == 401


async def test_admin_rejects_wrong_token(api):
    r = await api.post("/admin/users", json={"email": "a@b.com"},
                       headers={"X-Admin-Token": "wrong"})
    assert r.status_code == 401


async def test_create_user_then_issue_client_key_authenticates(api, admin_headers):
    r = await api.post("/admin/users", json={"email": "o@b.com", "display_name": "Owner"},
                       headers=admin_headers)
    assert r.status_code == 201
    uid = r.json()["id"]

    # duplicate email rejected
    dup = await api.post("/admin/users", json={"email": "o@b.com"}, headers=admin_headers)
    assert dup.status_code == 409

    issued = await api.post(f"/admin/users/{uid}/keys",
                            json={"kind": "client", "allowed_origins": ["*.x.com"]},
                            headers=admin_headers)
    assert issued.status_code == 201
    body = issued.json()
    assert body["key"].startswith("pk_live_") and body["last4"] == body["key"][-4:]

    # the freshly-issued raw key actually works against the auth surface
    who = await api.get("/v1/whoami", headers={
        "Authorization": f"Bearer {body['key']}", "Origin": "https://app.x.com"})
    assert who.status_code == 200 and who.json()["user_id"] == uid


async def test_issue_key_for_unknown_user_404(api, admin_headers):
    r = await api.post("/admin/users/99999/keys", json={"kind": "client"},
                       headers=admin_headers)
    assert r.status_code == 404


async def test_issue_key_rejects_bad_kind(api, admin_headers):
    uid = (await api.post("/admin/users", json={"email": "k@b.com"},
                          headers=admin_headers)).json()["id"]
    r = await api.post(f"/admin/users/{uid}/keys", json={"kind": "root"},
                       headers=admin_headers)
    assert r.status_code == 422


async def test_patch_key_revoke_invalidates(api, admin_headers):
    uid = (await api.post("/admin/users", json={"email": "p@b.com"},
                          headers=admin_headers)).json()["id"]
    issued = (await api.post(f"/admin/users/{uid}/keys",
                             json={"kind": "client", "allowed_origins": ["*.x.com"]},
                             headers=admin_headers)).json()
    h = {"Authorization": f"Bearer {issued['key']}", "Origin": "https://app.x.com"}
    assert (await api.get("/v1/whoami", headers=h)).status_code == 200

    revoked = await api.patch(f"/admin/keys/{issued['id']}", json={"action": "revoke"},
                              headers=admin_headers)
    assert revoked.status_code == 200 and revoked.json()["revoked"] is True
    assert (await api.get("/v1/whoami", headers=h)).status_code == 401


async def test_patch_key_rotate_returns_new_key(api, admin_headers):
    uid = (await api.post("/admin/users", json={"email": "r@b.com"},
                          headers=admin_headers)).json()["id"]
    kid = (await api.post(f"/admin/users/{uid}/keys",
                          json={"kind": "client", "allowed_origins": ["*.x.com"]},
                          headers=admin_headers)).json()["id"]
    r = await api.patch(f"/admin/keys/{kid}",
                        json={"allowed_origins": ["*.y.com"], "action": "rotate"},
                        headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["key"].startswith("pk_live_") and body["rotated_to"] != kid


async def test_list_users(api, admin_headers):
    await api.post("/admin/users", json={"email": "l@b.com"}, headers=admin_headers)
    r = await api.get("/admin/users", headers=admin_headers)
    assert r.status_code == 200
    assert any(u["email"] == "l@b.com" for u in r.json()["users"])


async def test_admin_console_is_served(api):
    r = await api.get("/admin/")
    assert r.status_code == 200
    assert "Demoviewer" in r.text and "Admin" in r.text  # the dashboard HTML
