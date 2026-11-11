"""Stage 06 — serving API end-to-end through the ASGI app (bunny mocked via a fake store).

Demos/rounds/refs are seeded directly through the repos (no parse), then read back through
`/v1/**` with a client key. Covers metadata + round index + map_ref + refs, by-ref resolution
+ cross-tenant 404, immutable round bytes + ETag/304, map calibration, listing pagination,
not-ready 409, and direct-vs-proxy parity.
"""
import hashlib
import os

import pytest

import app.serving.router as serving
from app.payload import build_index, decode_round, encode_round
from app.storage.object_store import round_key
from app.storage.repos import CollectionRepo, DemoRepo, RefRepo, RoundRepo, UserRepo

pytestmark = pytest.mark.e2e

PV = 1


class FakeStore:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes:
        return self.objects[key]

    async def put(self, key, data, **kw) -> str:
        self.objects[key] = bytes(data)
        return key


def _valid_record(round_index: int) -> dict:
    player = {
        "steamid": "111", "name": "p1", "X": 1.0, "Y": 2.0, "yaw": 0.0, "health": 100,
        "armor_value": 100, "balance": 800, "flash_duration": 0.0, "has_defuser": False,
        "has_helmet": True, "is_walking": False, "active_weapon_name": "ak47",
        "team_name": "t", "inventory": ["AK-47"],
    }
    return {"ticks": {100: {"players": [player], "weapon_fires": [], "bomb": None,
                            "grenades": []}},
            "meta": {"round_index": round_index, "winner": "t"},
            "smokes": [], "infernos": [], "kills": {}}


@pytest.fixture
def fake_store():
    store = FakeStore()
    from app.main import app
    app.dependency_overrides[serving.get_store] = lambda: store
    yield store
    app.dependency_overrides.pop(serving.get_store, None)


async def _client_key(api, admin_headers, email="serve@x.com"):
    uid = (await api.post("/admin/users", json={"email": email},
                          headers=admin_headers)).json()["id"]
    key = (await api.post(f"/admin/users/{uid}/keys",
                          json={"kind": "client", "allowed_origins": ["*.x.com"]},
                          headers=admin_headers)).json()["key"]
    return uid, key


async def _seed_ready_demo(pool, store, owner_uid, *, map_name="de_inferno",
                           n_rounds=2, refs=()):
    sha = hashlib.sha256(os.urandom(16)).hexdigest()  # unique per demo (sha256 is UNIQUE)
    demo_id = await DemoRepo(pool).create(owner_uid, sha, map_name, "Seed",
                                          status="queued", payload_version=PV)
    index_rounds = []
    for i in range(1, n_rounds + 1):
        blob = encode_round(_valid_record(i))
        key = round_key(demo_id, PV, i)
        store.objects[key] = blob
        meta = {"round_index": i, "winner": "t", "reason": "elimination",
                "T_score": i, "CT_score": 0}
        await RoundRepo(pool).upsert(demo_id, i, key, len(blob), meta)
        index_rounds.append({"round_index": i, "storage_key": key,
                             "byte_size": len(blob), "meta": meta})
    for source, ext in refs:
        await RefRepo(pool).add(demo_id, source, ext, owner_uid)
    await DemoRepo(pool).set_ready(demo_id, round_count=n_rounds, duration_ticks=5000,
                                   storage_key=f"{demo_id}/canonical.zip",
                                   meta={"steam": [{"steamid": "111", "personaname": "p1"}]})
    return demo_id


def _h(key):
    return {"Authorization": f"Bearer {key}", "Origin": "https://app.x.com"}


async def test_demo_metadata(api, admin_headers, db, fake_store):
    uid, key = await _client_key(api, admin_headers)
    demo_id = await _seed_ready_demo(db, fake_store, uid, refs=[("hltv", "2378001")])

    r = await api.get(f"/v1/demos/{demo_id}", headers=_h(key))
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == demo_id and body["map"] == "de_inferno"
    assert body["round_count"] == 2 and len(body["rounds"]) == 2
    assert body["refs"] == [{"source": "hltv", "external_id": "2378001"}]
    assert body["players"][0]["steamid"] == "111"
    assert body["map_ref"]["radar_url"] == "https://csstrats.b-cdn.net/maps/de_inferno.svg"
    assert r.headers["Cache-Control"] == "public, max-age=60"


async def test_by_ref_resolves_and_cross_tenant_404(api, admin_headers, db, fake_store):
    uid, key = await _client_key(api, admin_headers)
    demo_id = await _seed_ready_demo(db, fake_store, uid, refs=[("hltv", "2378001")])

    by_ref = await api.get("/v1/demos/by-ref/hltv/2378001", headers=_h(key))
    assert by_ref.status_code == 200
    assert by_ref.json()["id"] == demo_id

    # unknown ref → 404
    assert (await api.get("/v1/demos/by-ref/hltv/does-not-exist", headers=_h(key))).status_code == 404

    # another tenant cannot resolve it (404, not 403)
    _, key_b = await _client_key(api, admin_headers, email="other@x.com")
    assert (await api.get("/v1/demos/by-ref/hltv/2378001", headers=_h(key_b))).status_code == 404
    assert (await api.get(f"/v1/demos/{demo_id}", headers=_h(key_b))).status_code == 404


async def test_shared_demo_isolates_refs_per_tenant(api, admin_headers, db, fake_store):
    """A demo deduped/shared across tenants must not leak one tenant's refs (e.g. Steam share codes)
    to another: each sees only its own refs, and by-ref resolves only within the tenant."""
    uid_a, key_a = await _client_key(api, admin_headers, email="ta@x.com")
    uid_b, key_b = await _client_key(api, admin_headers, email="tb@x.com")

    demo_id = await _seed_ready_demo(db, fake_store, uid_a, refs=[("steam", "CODE-A")])
    # Simulate a cross-tenant dedup hit: B gains access and attaches ITS own ref to the same demo.
    await DemoRepo(db).grant_access(demo_id, uid_b)
    await RefRepo(db).add(demo_id, "steam", "CODE-B", uid_b)

    # Metadata body: each tenant sees only its own ref.
    a_refs = (await api.get(f"/v1/demos/{demo_id}", headers=_h(key_a))).json()["refs"]
    b_refs = (await api.get(f"/v1/demos/{demo_id}", headers=_h(key_b))).json()["refs"]
    assert a_refs == [{"source": "steam", "external_id": "CODE-A"}]
    assert b_refs == [{"source": "steam", "external_id": "CODE-B"}]

    # by-ref is tenant-scoped: neither tenant can resolve the other's code.
    assert (await api.get("/v1/demos/by-ref/steam/CODE-A", headers=_h(key_a))).status_code == 200
    assert (await api.get("/v1/demos/by-ref/steam/CODE-B", headers=_h(key_a))).status_code == 404
    assert (await api.get("/v1/demos/by-ref/steam/CODE-A", headers=_h(key_b))).status_code == 404
    assert (await api.get("/v1/demos/by-ref/steam/CODE-B", headers=_h(key_b))).status_code == 200


async def test_round_bytes_immutable_and_304(api, admin_headers, db, fake_store):
    uid, key = await _client_key(api, admin_headers)
    demo_id = await _seed_ready_demo(db, fake_store, uid)

    r = await api.get(f"/v1/demos/{demo_id}/rounds/1", headers=_h(key))
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    etag = r.headers["ETag"]
    assert etag
    # httpx transparently inflates Content-Encoding: gzip → the record the viewer parses
    assert r.json() == decode_round(encode_round(_valid_record(1)))

    # conditional request → 304, no body
    again = await api.get(f"/v1/demos/{demo_id}/rounds/1",
                          headers={**_h(key), "If-None-Match": etag})
    assert again.status_code == 304

    # unknown round → 404
    assert (await api.get(f"/v1/demos/{demo_id}/rounds/99", headers=_h(key))).status_code == 404


async def test_round_rate_limit_headers_present(api, admin_headers, db, fake_store):
    uid, key = await _client_key(api, admin_headers)
    demo_id = await _seed_ready_demo(db, fake_store, uid)
    r = await api.get(f"/v1/demos/{demo_id}/rounds/1", headers=_h(key))
    assert r.headers["X-RateLimit-Limit"] == "100"  # default client limit, headers survive


async def test_maps(api, admin_headers, db, fake_store):
    _, key = await _client_key(api, admin_headers)
    r = await api.get("/v1/maps/de_mirage", headers=_h(key))
    assert r.status_code == 200
    body = r.json()
    assert body["radar_url"] == "https://csstrats.b-cdn.net/maps/de_mirage.svg"
    assert body["scale"] == 5
    assert r.headers["Cache-Control"] == "public, max-age=86400"

    assert (await api.get("/v1/maps/de_notamap", headers=_h(key))).status_code == 404

    listed = await api.get("/v1/maps", headers=_h(key))
    assert listed.status_code == 200
    assert any(m["name"] == "de_nuke" and m["selections"] for m in listed.json()["items"])


async def test_unknown_map_returns_unsupported_state_not_500(api, admin_headers, db, fake_store):
    # A demo on a map with no map_metadata row must serve metadata with map_supported=false
    # and map_ref=null — a clear unsupported state, never a crash (Stage 12 §12.4).
    uid, key = await _client_key(api, admin_headers)
    demo_id = await _seed_ready_demo(db, fake_store, uid, map_name="de_communitymap42")
    r = await api.get(f"/v1/demos/{demo_id}", headers=_h(key))
    assert r.status_code == 200
    body = r.json()
    assert body["map_supported"] is False
    assert body["map_ref"] is None


async def test_not_ready_demo_returns_409(api, admin_headers, db, fake_store):
    uid, key = await _client_key(api, admin_headers)
    demo_id = await DemoRepo(db).create(uid, "b" * 64, "de_inferno", "WIP",
                                        status="parsing", payload_version=PV)
    r = await api.get(f"/v1/demos/{demo_id}", headers=_h(key))
    assert r.status_code == 409
    assert r.json()["status"] == "parsing"
    # round fetch on a not-ready demo is also a clean 409, not a 500
    assert (await api.get(f"/v1/demos/{demo_id}/rounds/1", headers=_h(key))).status_code == 409


async def test_listing_pagination_and_filters(api, admin_headers, db, fake_store):
    uid, key = await _client_key(api, admin_headers)
    ids = [await _seed_ready_demo(db, fake_store, uid, map_name="de_mirage", n_rounds=1)
           for _ in range(3)]

    page1 = (await api.get("/v1/demos?limit=2", headers=_h(key))).json()
    assert len(page1["items"]) == 2 and page1["next_cursor"] == page1["items"][-1]["id"]
    page2 = (await api.get(f"/v1/demos?limit=2&cursor={page1['next_cursor']}",
                           headers=_h(key))).json()
    assert len(page2["items"]) == 1 and page2["next_cursor"] is None
    # newest-first, no overlap
    seen = [i["id"] for i in page1["items"] + page2["items"]]
    assert sorted(seen, reverse=True) == seen and set(seen) == set(ids)

    # map filter matches all; a bogus map matches none
    assert len((await api.get("/v1/demos?map=de_mirage", headers=_h(key))).json()["items"]) == 3
    assert (await api.get("/v1/demos?map=de_dust2", headers=_h(key))).json()["items"] == []


async def test_bandwidth_cap_throttles_payloads(api, admin_headers, db, fake_store, monkeypatch):
    from app.config import settings
    uid, key = await _client_key(api, admin_headers)
    demo_id = await _seed_ready_demo(db, fake_store, uid)
    blob = fake_store.objects[round_key(demo_id, PV, 1)]
    # cap = one round's bytes → the first fetch fits, the second exceeds → 429 (Stage 13 §13.3)
    monkeypatch.setattr(settings, "bandwidth_cap_bytes", len(blob))

    r1 = await api.get(f"/v1/demos/{demo_id}/rounds/1", headers=_h(key))
    assert r1.status_code == 200
    r2 = await api.get(f"/v1/demos/{demo_id}/rounds/1", headers=_h(key))
    assert r2.status_code == 429 and int(r2.headers["Retry-After"]) > 0


async def test_metadata_mints_cdn_token_when_configured(api, admin_headers, db, fake_store, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "bunny_demos_cdn_host", "demos.b-cdn.net")
    monkeypatch.setattr(settings, "bunny_demos_token_key", "supersecret")
    uid, key = await _client_key(api, admin_headers)
    demo_id = await _seed_ready_demo(db, fake_store, uid)

    body = (await api.get(f"/v1/demos/{demo_id}", headers=_h(key))).json()
    assert body["cdn"]["base"] == "https://demos.b-cdn.net"
    assert body["cdn"]["token"] and body["cdn"]["token_path"] == f"/{demo_id}/v{PV}/"


async def test_metadata_cdn_null_without_token_key(api, admin_headers, db, fake_store, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "bunny_demos_token_key", "")   # not configured → fall back to API
    uid, key = await _client_key(api, admin_headers)
    demo_id = await _seed_ready_demo(db, fake_store, uid)
    body = (await api.get(f"/v1/demos/{demo_id}", headers=_h(key))).json()
    assert body["cdn"] is None


async def _seed_collection(db, store, uid, *, source="hltv", external_id="2378001",
                           maps=("de_nuke", "de_mirage")):
    cid = await CollectionRepo(db).get_or_create(uid, source=source, external_id=external_id,
                                                 name="match")
    ids = []
    for mp in maps:
        did = await _seed_ready_demo(db, store, uid, map_name=mp, n_rounds=1,
                                     refs=[(source, external_id)])
        await DemoRepo(db).set_collection(did, cid)
        ids.append(did)
    return cid, ids


async def test_by_ref_shared_id_disambiguated_by_map(api, admin_headers, db, fake_store):
    # Stage 18: one match id maps to several map demos; ?map= selects one (§18.3).
    uid, key = await _client_key(api, admin_headers, email="coll@x.com")
    _, ids = await _seed_collection(db, fake_store, uid)

    nuke = await api.get("/v1/demos/by-ref/hltv/2378001?map=de_nuke", headers=_h(key))
    assert nuke.status_code == 200 and nuke.json()["map"] == "de_nuke"
    mirage = await api.get("/v1/demos/by-ref/hltv/2378001?map=de_mirage", headers=_h(key))
    assert mirage.json()["map"] == "de_mirage"
    # without ?map → still resolves to one (back-compat), and it's one of the match's demos
    any_one = await api.get("/v1/demos/by-ref/hltv/2378001", headers=_h(key))
    assert any_one.json()["id"] in ids


async def test_collection_by_ref_returns_all_maps(api, admin_headers, db, fake_store):
    uid, key = await _client_key(api, admin_headers, email="coll2@x.com")
    cid, ids = await _seed_collection(db, fake_store, uid)

    r = await api.get("/v1/collections/by-ref/hltv/2378001", headers=_h(key))
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == cid and body["external_id"] == "2378001"
    assert {d["map"] for d in body["demos"]} == {"de_nuke", "de_mirage"}
    assert {d["id"] for d in body["demos"]} == set(ids)

    # by id works too; cross-tenant is 404
    assert (await api.get(f"/v1/collections/{cid}", headers=_h(key))).status_code == 200
    _, other = await _client_key(api, admin_headers, email="intruder@x.com")
    assert (await api.get(f"/v1/collections/{cid}", headers=_h(other))).status_code == 404
    assert (await api.get("/v1/collections/by-ref/hltv/2378001",
                          headers=_h(other))).status_code == 404


async def test_direct_vs_proxy_parity(api, admin_headers, db, fake_store):
    """A client key (direct) and a server key (proxy, with X-End-User) get identical bodies."""
    uid, ckey = await _client_key(api, admin_headers)
    demo_id = await _seed_ready_demo(db, fake_store, uid, refs=[("hltv", "9")])
    skey = (await api.post(f"/admin/users/{uid}/keys", json={"kind": "server"},
                           headers=admin_headers)).json()["key"]

    direct = await api.get(f"/v1/demos/{demo_id}", headers=_h(ckey))
    proxy = await api.get(f"/v1/demos/{demo_id}",
                          headers={"X-Server-Key": skey, "X-End-User": "fan-1"})
    assert direct.status_code == proxy.status_code == 200
    assert direct.json() == proxy.json()
    assert direct.headers["Cache-Control"] == proxy.headers["Cache-Control"]
