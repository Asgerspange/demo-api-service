"""Phase 03 — auth dependency end-to-end through the ASGI app (GET /v1/whoami)."""
import pytest

from app.auth.service import KeyService
from app.storage.repos import KeyRepo, UserRepo

pytestmark = pytest.mark.e2e


async def _issue(db, fake_redis, kind, email, **kw):
    """Create a user + issue a key directly (shares the app's DB pool + fake Redis)."""
    uid = await UserRepo(db).create(email)
    svc = KeyService(KeyRepo(db), fake_redis, cache_ttl=30, rotation_grace=86_400,
                     default_rate=100)
    key_id, gen = await svc.issue(uid, kind, **kw)
    return uid, key_id, gen, svc


async def test_client_key_allowed_origin_ok(api, db, fake_redis):
    uid, _, gen, _ = await _issue(db, fake_redis, "client", "c@x.com",
                                  allowed_origins=["*.example.com"])
    r = await api.get("/v1/whoami", headers={
        "Authorization": f"Bearer {gen.raw}", "Origin": "https://app.example.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "client" and body["user_id"] == uid


async def test_client_key_wrong_origin_403(api, db, fake_redis):
    _, _, gen, _ = await _issue(db, fake_redis, "client", "c@x.com",
                                allowed_origins=["*.example.com"])
    r = await api.get("/v1/whoami", headers={
        "Authorization": f"Bearer {gen.raw}", "Origin": "https://evil.com"})
    assert r.status_code == 403


async def test_client_key_accepts_x_client_key_header(api, db, fake_redis):
    _, _, gen, _ = await _issue(db, fake_redis, "client", "c@x.com",
                                allowed_origins=["*.example.com"])
    r = await api.get("/v1/whoami", headers={
        "X-Client-Key": gen.raw, "Origin": "https://app.example.com"})
    assert r.status_code == 200


async def test_missing_key_401(api):
    assert (await api.get("/v1/whoami")).status_code == 401


async def test_unknown_key_401(api):
    r = await api.get("/v1/whoami", headers={
        "Authorization": "Bearer pk_live_nope", "Origin": "https://app.example.com"})
    assert r.status_code == 401


async def test_server_key_with_browser_origin_400(api, db, fake_redis):
    _, _, gen, _ = await _issue(db, fake_redis, "server", "s@x.com")
    r = await api.get("/v1/whoami", headers={
        "X-Server-Key": gen.raw, "Origin": "https://app.example.com", "X-End-User": "u1"})
    assert r.status_code == 400


async def test_server_key_requires_end_user_400(api, db, fake_redis):
    _, _, gen, _ = await _issue(db, fake_redis, "server", "s@x.com")
    r = await api.get("/v1/whoami", headers={"X-Server-Key": gen.raw})
    assert r.status_code == 400


async def test_server_key_from_backend_ok(api, db, fake_redis):
    uid, _, gen, _ = await _issue(db, fake_redis, "server", "s@x.com")
    r = await api.get("/v1/whoami", headers={
        "X-Server-Key": gen.raw, "X-End-User": "user-42"})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "server" and body["end_user"] == "user-42"
    assert body["user_id"] == uid


async def test_revoked_key_401(api, db, fake_redis):
    _, kid, gen, svc = await _issue(db, fake_redis, "client", "c@x.com",
                                    allowed_origins=["*.example.com"])
    h = {"Authorization": f"Bearer {gen.raw}", "Origin": "https://app.example.com"}
    assert (await api.get("/v1/whoami", headers=h)).status_code == 200
    await svc.revoke(kid)
    assert (await api.get("/v1/whoami", headers=h)).status_code == 401


async def test_rotation_old_and_new_valid_in_grace(api, db, fake_redis):
    _, kid, gen, svc = await _issue(db, fake_redis, "client", "c@x.com",
                                    allowed_origins=["*.example.com"])
    _, new_gen = await svc.rotate(kid)
    h_old = {"Authorization": f"Bearer {gen.raw}", "Origin": "https://app.example.com"}
    h_new = {"Authorization": f"Bearer {new_gen.raw}", "Origin": "https://app.example.com"}
    assert (await api.get("/v1/whoami", headers=h_old)).status_code == 200
    assert (await api.get("/v1/whoami", headers=h_new)).status_code == 200
