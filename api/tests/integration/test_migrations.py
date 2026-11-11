"""Phase 02 — migrations apply + map_metadata seed (real test MySQL)."""
import pytest

from app.storage.migrate import MIGRATIONS_DIR, apply_migrations
from app.storage.repos import MapRepo

pytestmark = pytest.mark.integration

EXPECTED_TABLES = {
    "users", "api_keys", "demos", "demo_rounds", "demo_external_refs",
    "map_metadata", "ingest_jobs", "schema_migrations",
}


async def _table_names(pool) -> set[str]:
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SHOW TABLES")
            return {row[0] for row in await cur.fetchall()}


async def test_migrations_create_all_tables_and_seed(empty_db):
    applied = await apply_migrations(empty_db)
    # Applies every migration file, in order (001 schema, 002 seed, 003 key rotation, …).
    assert applied == sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
    assert EXPECTED_TABLES <= await _table_names(empty_db)

    maps = MapRepo(empty_db)
    # map_metadata.sql ships 15 rows (id 15 was deleted upstream; AUTO_INCREMENT=17).
    assert await maps.count() == 15

    mirage = await maps.get("de_mirage")
    assert mirage["is_active_duty"] == 1
    assert mirage["scale"] == 5
    assert mirage["pos_x"] == -3230
    assert mirage["image_path"].endswith("de_mirage.svg")

    # Multi-level map: selections JSON decoded into a Python list.
    nuke = await maps.get("de_nuke")
    assert isinstance(nuke["selections"], list)
    assert {s["name"] for s in nuke["selections"]} == {"default", "lower"}


async def test_map_name_is_unique(db):
    with pytest.raises(Exception):  # duplicate `name` violates uq
        async with db.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO map_metadata (map_id, name, pos_x, pos_y, scale) "
                    "VALUES (1, 'de_mirage', 0, 0, 1)"
                )
            await conn.commit()


async def test_migrations_are_idempotent(empty_db):
    first = await apply_migrations(empty_db)
    assert first  # applied something
    assert await apply_migrations(empty_db) == []  # nothing pending on re-run
