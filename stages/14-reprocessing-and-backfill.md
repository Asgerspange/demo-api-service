# Stage 14 — Reprocessing & Backfill

**Goal:** regenerate derived data across the whole demo library — cheaply when possible,
deeply when necessary — without disrupting live ingestion.

## Context

You keep the parquet (warm) and raw `.dem` (cold) precisely so you can reprocess. This stage
is the orchestration that was implied but never specced. You **will** need it the first time
you bump `payload_version` or patch the parser (≈ every CS2 update).

## 14.1 Two reprocess paths

- **Cheap — re-derive payloads from parquet.** For payload-format changes (`payload_version`
  bump) that need no new fields. Read `canonical.zip`, rebuild per-round payloads, upload new
  objects. No re-parse, no raw `.dem` fetch. Fast and cheap.
- **Deep — re-parse from raw `.dem`.** For parser fixes, corrected values, or **new fields**
  not present in the parquet. Pull the cold archive (Stage 10), decompress, re-parse with the
  current awpy, regenerate parquet **and** payloads. Expensive; use only when the cheap path
  can't supply the data.

The job picks the path from the migration's needs (a flag: `needs_reparse`).

## 14.2 `payload_version` migration (zero-downtime)

- Write the new version **alongside** the old: `demos/{id}/v{N+1}/…` while `v{N}` still
  serves. Demos flip to the new version (update `demos.payload_version` + `index.json`) only
  once their `v{N+1}` is complete and verified.
- Old viewers pinned to `v{N}` keep working until you sunset it (Stage 17 deprecation policy).
- **GC** old-version objects after cutover + grace window.

## 14.3 Backfill orchestrator

- Enqueue the target demo set on a **low-priority lane** (Stage 16) so live ingestion always
  wins; throttle concurrency to a configured ceiling.
- **Idempotent + resumable**: track per-demo backfill state (pending/done/failed) so a
  restart continues, not restarts. Re-running is safe.
- **Progress + observability**: total/done/failed, ETA, failures with demo id + stage. Expose
  in the admin (Stage 03).
- **Verification** before flip: sanity-check the regenerated payload (round count, sizes,
  a checksum) so a bad batch can't replace good data.

## Reuse from existing code

- `demo_processor.py` payload-building functions → the re-derive core (parametrized by
  `payload_version`).
- Stage 05 parse pipeline → the deep re-parse path.
- `demo_service.cleanup_chunks` spirit → old-version GC sweep.

## Acceptance criteria

- **Tests (required for Done):** the tests this phase needs are written and green in CI — see
  `TESTING.md` for stack/layout and its per-phase table for exactly what to cover.

- Bumping `payload_version` backfills the whole library from parquet without delaying any
  live ingest, then flips demos to the new version and GCs the old.
- A parser-fix backfill re-parses from the cold raw `.dem` and updates parquet + payloads.
- Backfill is resumable after a kill and never double-charges a completed demo.
- A regenerated batch that fails verification does not replace the live version.
