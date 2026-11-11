"""Disaster recovery — rebuild the demo→object mapping from storage (Stage 16 §16.3).

The DB holds the demo→object mapping; the parquet/payload/raw archives are useless without it.
Primary recovery is a DB restore from backup (see `deploy/DR.md`). This module is the documented
**rebuild path** for the worst case where the mapping is lost but the objects survive: scan the
demos zone for each demo's `index.json`, and re-create the `demos` + `demo_rounds` rows pointing at
the surviving payload objects. sha256/owner can't be recovered from storage, so a synthetic sha and
an operator-chosen owner are used, and the row is flagged `meta.rebuilt_from_storage` for audit.

Pure-ish: takes any object store exposing `list_keys`/`get`, so it's tested against a fake store.
"""
from __future__ import annotations

import hashlib

import orjson

from .storage.object_store import canonical_key
from .storage.repos import RoundRepo


def _synthetic_sha(demo_id: int) -> str:
    """A stable, unique placeholder sha256 for a rebuilt demo (the real one is unrecoverable)."""
    return hashlib.sha256(f"rebuilt:{demo_id}".encode()).hexdigest()


async def _upsert_rebuilt_demo(pool, *, demo_id: int, owner_user_id: int, map_name: str,
                               payload_version: int, round_count: int) -> None:
    """Re-create one `demos` row with an explicit id, idempotently (DR — explicit SQL)."""
    meta = orjson.dumps({"rebuilt_from_storage": True}).decode()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO demos (id, owner_user_id, sha256, map, name, status, "
                "payload_version, round_count, storage_key, meta, ready_at) "
                "VALUES (%s, %s, %s, %s, %s, 'ready', %s, %s, %s, %s, CURRENT_TIMESTAMP) "
                "ON DUPLICATE KEY UPDATE status='ready', map=VALUES(map), "
                "payload_version=VALUES(payload_version), round_count=VALUES(round_count), "
                "storage_key=VALUES(storage_key), meta=VALUES(meta)",
                (demo_id, owner_user_id, _synthetic_sha(demo_id), map_name,
                 f"rebuilt demo {demo_id}", payload_version, round_count,
                 canonical_key(demo_id), meta),
            )
        await conn.commit()


async def rebuild_from_storage(pool, store, *, owner_user_id: int,
                               payload_version: int | None = None) -> dict:
    """Scan the demos zone and re-derive `demos` + `demo_rounds` rows from each `index.json`.

    `owner_user_id` is assigned as the recovered demos' owner (the operator picks a recovery
    account). With `payload_version` set, only indexes at that version are rebuilt. Returns a
    summary (indexes found, demos + rounds rebuilt).
    """
    keys = await store.list_keys("")
    indexes = [k for k in keys if k.endswith("/index.json")]

    rounds_repo = RoundRepo(pool)
    demos_rebuilt = rounds_rebuilt = 0
    for ik in indexes:
        index = orjson.loads(await store.get(ik))
        pv = int(index["payload_version"])
        if payload_version is not None and pv != payload_version:
            continue
        demo_id = int(index["demo_id"])
        rounds = index.get("rounds", [])
        await _upsert_rebuilt_demo(pool, demo_id=demo_id, owner_user_id=owner_user_id,
                                   map_name=index["map"], payload_version=pv,
                                   round_count=len(rounds))
        for r in rounds:
            await rounds_repo.upsert(demo_id, int(r["round_index"]), r["key"],
                                     int(r["byte_size"]), r.get("meta") or {})
            rounds_rebuilt += 1
        demos_rebuilt += 1

    return {"indexes_found": len(indexes), "demos_rebuilt": demos_rebuilt,
            "rounds_rebuilt": rounds_rebuilt}
