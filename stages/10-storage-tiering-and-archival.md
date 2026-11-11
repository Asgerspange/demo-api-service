# Stage 10 — Storage Tiering & Demo Archival

**Goal:** keep exactly what we need to reprocess a demo forever, in the cheapest place that
still meets its read frequency. Settles the "store the raw `.dem`?" question.

## Context

Three artifacts exist per demo, with different value and read patterns. The earlier plan
treated the parquet zip as the source of truth — it isn't. The parquet only holds the fields
awpy extracted at parse time (the finite `_player_props` list, current parser behavior), so
it cannot yield new/corrected fields later. The **raw `.dem` is the real source of truth**;
the parquet is a warm cache that saves parse CPU.

## 10.1 The three tiers

| Tier | Artifact | Storage | Read pattern | Purpose |
|------|----------|---------|--------------|---------|
| **Hot** | per-round payloads | bunny `demos` zone (geo-repl LA/NY/FRA) + CDN | constant | drives the viewer |
| **Warm** | `Demo.compress()` parquet zip (~10 MB) | single-region cheap bucket | occasional | re-derive payloads w/o re-parsing |
| **Cold** | compressed raw `.dem` (~40–60 MB) | cheapest archival (single-region bunny / Backblaze B2 / S3 Glacier Deep Archive) | rare | re-parse for new/corrected fields |

Do **not** place warm/cold artifacts in the geo-replicated `demos` zone — replication bills
~3–4× per GB for data read once a year.

## 10.2 Raw `.dem` archival

- **Compress** with `zstd --ultra -22 --long=31` (lossless; ~3–5× on CS2 demos). Reuse the
  `zstandard` dep + the streaming approach already in `demo_processor.py`.
- **Stream** compression on the worker during ingest so a 200 MB+ demo never fully loads
  into memory. Compress straight to the archive upload.
- **Dedup** by `demos.sha256` (already enforced) — store each unique demo once even if
  submitted by multiple integrators (HLTV + FACEIT same match).
- **Codec field** for forward-compat (`raw_codec='zstd'`) so a future codec swap is safe.

## 10.3 DB additions (extend `demos`, Stage 02)

```sql
ALTER TABLE demos
  ADD COLUMN raw_storage_key VARCHAR(512),    -- cold archive key of the compressed .dem
  ADD COLUMN raw_codec       VARCHAR(16),     -- 'zstd'
  ADD COLUMN raw_bytes       BIGINT,          -- compressed size, for cost tracking
  ADD COLUMN retention_tier  VARCHAR(16) NOT NULL DEFAULT 'standard';  -- standard|archive|ephemeral
```
`storage_key` (parquet) and `raw_storage_key` (raw) are separate. `retention_tier` is the
mechanism for later lifecycle policy (keep raw long for paid, drop for free/ephemeral).

## 10.4 Keep both, or raw-only? (decision)

- **Both (recommended):** parquet makes the *common* reprocess (payload-format change) cheap
  — no re-parse. Raw is the *rare* escape hatch (parser fixes, new fields). Parquet is small,
  so warm storage is cheap insurance against big CPU bills at scale.
- **Raw-only (simpler):** one source of truth; every reprocess pays full parse CPU. Fine at
  low volume; expensive when backfilling 100k demos. Choose this only if parse is cheap and
  reprocesses are infrequent.

Default to **both**. Stage 14 consumes both paths.

## 10.5 Lifecycle (mechanism now, policy later)

- Lifecycle rules drive cold storage to deep-archive / deletion by `retention_tier` and age.
- Deletion (Stage 08) must purge **all three** tiers + DB rows. Add the cold key to the
  delete sweep.

## Reuse from existing code

- `demo_processor.py` (zstd streaming in `process_demo_from_chunks`) → streaming compressor.
- `Demo.compress()` → warm parquet artifact (unchanged).

## Acceptance criteria

- **Tests (required for Done):** the tests this phase needs are written and green in CI — see
  `TESTING.md` for stack/layout and its per-phase table for exactly what to cover.

- Ingest writes 3 artifacts to 3 tiers; `demos` rows carry both `storage_key` and
  `raw_storage_key`.
- The same demo submitted twice is stored once (sha256 dedup) across all tiers.
- A cold raw `.dem` round-trips: download → decompress → byte-identical to the original.
- Documented cost-per-demo per tier.
- Demo deletion removes hot + warm + cold objects and the DB rows.
