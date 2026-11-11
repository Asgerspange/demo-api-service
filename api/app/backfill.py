"""Reprocessing & backfill (Stage 14).

Regenerate derived data across the library without disrupting live ingest:

- **cheap** — re-derive per-round payloads from the warm `canonical.zip` (parquet). No re-parse,
  no raw fetch. For `payload_version` bumps / payload-format changes.
- **deep**  — re-parse from the cold raw `.dem` (new/corrected fields), regenerating parquet +
  payloads. Expensive; only when the cheap path can't supply the data.

Zero-downtime (§14.2): write `v{target}` ALONGSIDE the current version, **verify**, flip
`demos.payload_version`, then GC the old objects. A batch that fails verification never replaces
the live version. Per-demo state (`backfill_demos`) makes a run idempotent + resumable.
"""
from __future__ import annotations

import asyncio
import os
import tempfile

import orjson

from .config import settings
from .ingest.archive import decompress_raw
from .ingest.canonical import frames_from_zip, frames_to_zip
from .ingest.rounds import build_round_records
from .payload import PayloadError, build_index, encode_round, validate_round
from .storage.object_store import ObjectStore, canonical_key, index_key, round_key
from .storage.repos import BackfillRepo, DemoRepo, RoundRepo


class BackfillVerifyError(Exception):
    """A regenerated batch failed verification — it must NOT replace the live version."""


def verify_records(records, *, expected_count: int | None) -> None:
    """Sanity-check regenerated payloads before any flip (§14.3): non-empty, viewer-valid, and
    the same round count as the live demo."""
    if not records:
        raise BackfillVerifyError("no rounds produced")
    for rec in records:
        try:
            validate_round(rec.record)
        except PayloadError as exc:
            raise BackfillVerifyError(f"round {rec.round_index} invalid: {exc}") from exc
    if expected_count is not None and len(records) != expected_count:
        raise BackfillVerifyError(
            f"round count {len(records)} != live {expected_count}"
        )


def _rederive_cheap(canonical_bytes: bytes):
    """Cheap path: canonical parquet → Frames → records (no re-parse)."""
    return build_round_records(frames_from_zip(canonical_bytes)), None


def _rederive_deep(raw_bytes: bytes, parse_fn):
    """Deep path: raw .dem → re-parse → records + a freshly-regenerated canonical zip."""
    from .ingest.rounds import frames_from_demo

    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "demo.dem")
        with open(path, "wb") as fp:
            fp.write(raw_bytes)
        dem = parse_fn(path)
    frames = frames_from_demo(dem)
    return build_round_records(frames), frames_to_zip(frames)


async def gc_version(pool, demo_id: int, old_pv: int, *, store: ObjectStore) -> int:
    """Delete a demo's objects for a superseded payload version (§14.2 GC, run after the grace
    window so viewers pinned to the old version keep working until then). Returns #objects removed."""
    rounds = await RoundRepo(pool).list_for_demo(demo_id)
    n = 0
    for r in rounds:
        await store.delete(round_key(demo_id, old_pv, r["round_index"])); n += 1
    await store.delete(index_key(demo_id, old_pv)); n += 1
    return n


async def backfill_demo(pool, demo_id: int, run_id: int, *, store: ObjectStore,
                        archive: ObjectStore, target_pv: int, mode: str = "cheap",
                        parse_fn=None, gc_old: bool = False) -> str:
    """Reprocess one demo to `target_pv`. Returns the terminal state (done/failed/skipped).

    Writes `v{target}` alongside the current version and flips only after verification. The old
    version is KEPT by default (grace window for viewers pinned to it, §14.2) — pass `gc_old=True`
    or run `gc_version()` separately to reclaim it. Idempotency is driven by `backfill_demos.state`
    (the caller skips non-pending demos); a forced re-run is safe (GC is guarded on old_pv != target).
    """
    bf, demos, rounds = BackfillRepo(pool), DemoRepo(pool), RoundRepo(pool)
    demo = await demos.get(demo_id)
    if demo is None or demo["status"] != "ready":
        await bf.mark(run_id, demo_id, "skipped", "demo missing or not ready")
        return "skipped"

    old_pv = demo["payload_version"]
    try:
        # 1. Regenerate records (+ canonical for deep).
        if mode == "deep":
            raw = decompress_raw(await archive.get(demo["raw_storage_key"]))
            if parse_fn is None:
                from .ingest.pipeline import _default_parse as parse_fn  # noqa: N806
            records, new_canonical = await asyncio.to_thread(_rederive_deep, raw, parse_fn)
        else:
            canonical = await archive.get(demo.get("storage_key") or canonical_key(demo_id))
            records, new_canonical = await asyncio.to_thread(_rederive_cheap, canonical)

        # 2. Verify BEFORE touching the live version.
        verify_records(records, expected_count=demo["round_count"])

        # 3. Write v{target} alongside the current version.
        new_rounds = []
        for rec in records:
            blob = encode_round(rec.record, level=settings.payload_gzip_level)
            key = round_key(demo_id, target_pv, rec.round_index)
            await store.put(key, blob)
            new_rounds.append({"round_index": rec.round_index, "storage_key": key,
                               "byte_size": len(blob), "meta": rec.light_meta})
        index = build_index(demo_id, demo["map"], new_rounds, payload_version=target_pv,
                            api_version=settings.api_version)
        await store.put(index_key(demo_id, target_pv), orjson.dumps(index),
                        content_type="application/json")
        if new_canonical is not None:
            await archive.put(canonical_key(demo_id), new_canonical, content_type="application/zip")

        # 4. Flip: point demo_rounds at the new keys + bump payload_version.
        for r in new_rounds:
            await rounds.upsert(demo_id, r["round_index"], r["storage_key"], r["byte_size"], r["meta"])
        await demos.set_payload_version(demo_id, target_pv)

        # 5. Old version is kept by default (grace window, §14.2). Opt-in immediate GC, guarded
        #    so a forced re-run (old_pv already == target) can't delete the just-written objects.
        if gc_old and old_pv != target_pv:
            for r in new_rounds:
                await store.delete(round_key(demo_id, old_pv, r["round_index"]))
            await store.delete(index_key(demo_id, old_pv))

        await bf.mark(run_id, demo_id, "done")
        return "done"
    except Exception as exc:  # noqa: BLE001 — record + continue; never poison the run
        await bf.mark(run_id, demo_id, "failed", f"{type(exc).__name__}: {exc}")
        return "failed"


async def run_backfill(pool, run_id: int, *, store: ObjectStore, archive: ObjectStore,
                       target_pv: int, mode: str = "cheap", parse_fn=None,
                       gc_old: bool = False) -> dict:
    """Process every still-pending demo in a run, then finalize the run status. Resumable: a
    re-invocation only picks up demos still `pending`."""
    bf = BackfillRepo(pool)
    for demo_id in await bf.pending(run_id):
        await backfill_demo(pool, demo_id, run_id, store=store, archive=archive,
                            target_pv=target_pv, mode=mode, parse_fn=parse_fn, gc_old=gc_old)
    counts = await bf.counts(run_id)
    await bf.set_run_status(run_id, "failed" if counts.get("failed") else "done")
    return counts


async def backfill_demo_task(ctx: dict, run_id: int, demo_id: int, target_pv: int,
                             mode: str) -> str:
    """arq task — one demo of a backfill run (enqueued per demo; wired in app/worker.py)."""
    return await backfill_demo(ctx["pool"], demo_id, run_id, store=ctx["store"],
                               archive=ctx["archive"], target_pv=target_pv, mode=mode)
