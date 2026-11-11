"""Stage 08 §8.4 — demo deletion provably removes every object (hot+warm+cold) + DB rows."""
import hashlib
import os

import pytest

import app.serving.router as serving
from app.payload import encode_round
from app.storage.object_store import canonical_key, index_key, round_key
from app.storage.repos import DemoRepo, RefRepo, RoundRepo, UserRepo

pytestmark = pytest.mark.e2e
PV = 1


class FakeStore:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    async def get(self, key):
        return self.objects[key]

    async def put(self, key, data, **kw):
        self.objects[key] = bytes(data); return key

    async def delete(self, key):
        self.objects.pop(key, None)


@pytest.fixture
def stores():
    store, archive = FakeStore(), FakeStore()
    from app.main import app
    app.dependency_overrides[serving.get_store] = lambda: store
    app.dependency_overrides[serving.get_archive_store] = lambda: archive
    yield store, archive
    app.dependency_overrides.pop(serving.get_store, None)
    app.dependency_overrides.pop(serving.get_archive_store, None)


async def _key(api, admin_headers, email, kind="server"):
    uid = (await api.post("/admin/users", json={"email": email}, headers=admin_headers)).json()["id"]
    body = {"kind": kind}
    if kind == "client":
        body["allowed_origins"] = ["*.x.com"]
    key = (await api.post(f"/admin/users/{uid}/keys", json=body, headers=admin_headers)).json()["key"]
    return uid, key


async def _seed(pool, store, archive, uid, n_rounds=3):
    sha = hashlib.sha256(os.urandom(16)).hexdigest()
    demo_id = await DemoRepo(pool).create(uid, sha, "de_inferno", "Seed", status="queued", payload_version=PV)
    for i in range(1, n_rounds + 1):
        blob = encode_round({"ticks": {1: {"players": [{
            "steamid": "1", "name": "p", "X": 0.0, "Y": 0.0, "yaw": 0.0, "health": 100,
            "armor_value": 0, "balance": 0, "flash_duration": 0.0, "has_defuser": False,
            "has_helmet": False, "is_walking": False, "active_weapon_name": "ak47",
            "team_name": "t", "inventory": []}], "weapon_fires": [], "bomb": None, "grenades": []}},
            "meta": {}, "smokes": [], "infernos": [], "kills": {}})
        key = round_key(demo_id, PV, i)
        store.objects[key] = blob                          # demos zone (served)
        await RoundRepo(pool).upsert(demo_id, i, key, len(blob), {"round_index": i})
    store.objects[index_key(demo_id, PV)] = b"{}"          # demos zone (served)
    archive.objects[canonical_key(demo_id)] = b"PK"        # cold zone (canonical)
    archive.objects[f"{demo_id}/raw.dem.zst"] = b"zstd"    # cold zone (raw)
    await RefRepo(pool).add(demo_id, "hltv", str(demo_id), uid)
    await DemoRepo(pool).set_ready(demo_id, round_count=n_rounds, duration_ticks=10,
                                   storage_key=canonical_key(demo_id), meta={})
    await DemoRepo(pool).set_raw_archive(demo_id, raw_storage_key=f"{demo_id}/raw.dem.zst",
                                         raw_codec="zstd", raw_bytes=4)
    return demo_id


# Deletion requires a SERVER (secret) key — server-key headers (no browser Origin).
def _sh(key):
    return {"X-Server-Key": key, "X-End-User": "backend-1"}


async def test_delete_purges_all_tiers_and_rows(api, admin_headers, db, stores):
    store, archive = stores
    uid, key = await _key(api, admin_headers, "del@x.com", kind="server")
    demo_id = await _seed(db, store, archive, uid)

    # demos zone: 3 rounds + index = 4 (served) ; cold archive: canonical + raw = 2
    assert len(store.objects) == 4 and len(archive.objects) == 2

    r = await api.request("DELETE", f"/v1/demos/{demo_id}", headers=_sh(key))
    assert r.status_code == 200 and r.json()["deleted"] is True

    # every object gone from both stores
    assert store.objects == {} and archive.objects == {}
    # rows gone (rounds + refs cascade)
    assert await DemoRepo(db).get(demo_id) is None
    assert await RoundRepo(db).list_for_demo(demo_id) == []
    assert await RefRepo(db).resolve("hltv", str(demo_id), uid) is None


async def test_delete_rejected_for_client_key(api, admin_headers, db, stores):
    # A public client key must NOT be able to delete — server key only (Stage 13 hardening).
    store, archive = stores
    uid, ckey = await _key(api, admin_headers, "ck@x.com", kind="client")
    demo_id = await _seed(db, store, archive, uid)

    r = await api.request("DELETE", f"/v1/demos/{demo_id}",
                          headers={"Authorization": f"Bearer {ckey}", "Origin": "https://app.x.com"})
    assert r.status_code == 403
    # nothing removed
    assert len(store.objects) == 4 and len(archive.objects) == 2
    assert await DemoRepo(db).get(demo_id) is not None


async def test_delete_cross_tenant_404_and_leaves_objects(api, admin_headers, db, stores):
    store, archive = stores
    uid_a, _ = await _key(api, admin_headers, "a@x.com", kind="server")
    demo_id = await _seed(db, store, archive, uid_a)
    _, key_b = await _key(api, admin_headers, "b@x.com", kind="server")

    r = await api.request("DELETE", f"/v1/demos/{demo_id}", headers=_sh(key_b))
    assert r.status_code == 404
    # nothing removed
    assert len(store.objects) == 4 and len(archive.objects) == 2
    assert await DemoRepo(db).get(demo_id) is not None
