"""Stage 12 — map calibration versioning: (name, version) resolution + data-driven add/recalibrate."""
import pytest

from app.storage.repos import MapRepo

pytestmark = pytest.mark.integration


async def test_migration_adds_version_and_seed_is_live(db):
    inferno = await MapRepo(db).get("de_inferno")
    assert inferno is not None and inferno["version"] == "live"


async def test_versioned_resolution_and_fallback(db):
    maps = MapRepo(db)
    # add a reworked calibration that coexists with the seeded 'live' one
    await maps.upsert("de_inferno", version="2024-rework",
                      pos_x=-2000, pos_y=4000, scale=5.0, rotate=0, zoom=0,
                      image_path="https://csstrats.b-cdn.net/maps/de_inferno_v2.svg")

    exact = await maps.get("de_inferno", version="2024-rework")
    assert exact["pos_x"] == -2000 and exact["version"] == "2024-rework"

    # an unknown version falls back to the best known (live), never None for a known map
    fb = await maps.get("de_inferno", version="does-not-exist")
    assert fb is not None and fb["version"] == "live"

    # both calibrations now coexist (unique relaxed to (name, version))
    rows = [m for m in await maps.list_all() if m["name"] == "de_inferno"]
    assert {r["version"] for r in rows} == {"live", "2024-rework"}


async def test_add_new_map_no_code_change(db):
    maps = MapRepo(db)
    assert await maps.get("de_brandnew") is None
    await maps.upsert("de_brandnew", pos_x=0, pos_y=0, scale=5, rotate=0, zoom=0,
                      display_name="Brand New", is_active_duty=1, selections=[],
                      image_path="https://csstrats.b-cdn.net/maps/de_brandnew.svg")
    row = await maps.get("de_brandnew")
    assert row is not None and row["image_path"].endswith("de_brandnew.svg")
    assert row["selections"] == []


async def test_admin_upsert_map_endpoint(api, admin_headers, db):
    r = await api.post("/admin/maps", headers=admin_headers, json={
        "name": "de_adminmap", "pos_x": 1.0, "pos_y": 2.0, "scale": 5.0,
        "image_path": "https://csstrats.b-cdn.net/maps/de_adminmap.svg", "is_active_duty": True,
    })
    assert r.status_code == 201 and r.json()["saved"] is True
    row = await MapRepo(db).get("de_adminmap")
    assert row is not None and row["pos_x"] == 1.0

    # admin-gated
    assert (await api.post("/admin/maps", json={"name": "x", "pos_x": 0, "pos_y": 0, "scale": 1})).status_code == 401
