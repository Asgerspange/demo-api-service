"""Demo deletion + orphan cleanup (Stage 08 §8.4).

"Delete my demo" must remove **every** associated object across all three storage tiers
(hot per-round payloads, warm canonical.zip, cold raw archive) **and** the DB rows — provably,
so nothing is left to leak or bill for (gap #16). Deletion returns the exact keys it removed so
callers/tests can verify completeness.

Object deletes are idempotent (ObjectStore.delete treats 404 as success), so a partial prior
delete can be re-run safely.
"""
from __future__ import annotations

from .storage.object_store import ObjectStore, canonical_key, index_key
from .storage.repos import DemoRepo, JobRepo, RoundRepo


async def collect_demo_keys(pool, demo: dict) -> dict[str, list[str]]:
    """Every object key a demo owns, split by store: the `demos` zone (served — per-round
    payloads + index.json) and the cold `archive` zone (reprocess — canonical.zip + raw .dem)."""
    demo_id = demo["id"]
    pv = demo["payload_version"]
    rounds = await RoundRepo(pool).list_for_demo(demo_id)

    demos_zone = [r["storage_key"] for r in rounds]            # per-round payloads (served)
    demos_zone.append(index_key(demo_id, pv))                  # index.json (served)
    cold = [demo.get("storage_key") or canonical_key(demo_id)]  # canonical.zip (cold)
    if demo.get("raw_storage_key"):
        cold.append(demo["raw_storage_key"])                   # raw .dem (cold)
    return {"demos_zone": demos_zone, "cold": cold}


async def delete_demo(demo_id: int, *, pool, store: ObjectStore,
                      archive: ObjectStore) -> dict | None:
    """Purge a demo's objects (demos zone + cold archive) + DB rows. Returns the deleted keys,
    or None if the demo doesn't exist. Objects are deleted first; if any delete raises, the rows
    are left intact so the operation can be retried (no half-deleted, un-findable objects)."""
    demo = await DemoRepo(pool).get(demo_id)
    if demo is None:
        return None

    keys = await collect_demo_keys(pool, demo)
    for key in keys["demos_zone"]:
        await store.delete(key)
    for key in keys["cold"]:
        await archive.delete(key)

    # Clear the no-cascade ingest_jobs.demo_id FK, then delete the demo (rounds + refs cascade).
    await JobRepo(pool).clear_demo(demo_id)
    await DemoRepo(pool).delete(demo_id)

    return {"demo_id": demo_id, "deleted_keys": keys}
