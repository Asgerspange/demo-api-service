# Stage 05 — Ingestion Pipeline

**Goal:** take a demo from a download URL (gzip/zip/rar/.dem) **or** a local path (debug),
parse it with awpy on a worker, produce the canonical parquet zip + per-round payloads, and
store everything. Async, idempotent, abuse-resistant.

## Context

Brief: *"a demo ingester that takes a download link to a gzip/zip/rar/.dem and parses it.
Also a path for debugging. Then save in db OR use dem.compress (parquet zip, ~10 MB)."*

Port the heavy lifting from `demoparser/demo_processor.py` — but move it onto an **arq
worker** instead of the APScheduler-in-the-API-process design.

## 5.1 Intake API (runs in the API process, fast)

```
POST /ingest            { source: {type:'url'|'path', ref:'…'}, name?, webhook_url?,
                          refs?: [ {source:'hltv', external_id:'2378001'} ] }
                        -> 202 { job_id }
GET  /ingest/{job_id}   -> { status, demo_id?, progress, error? }
```
- `refs` attaches external identifiers (Stage 02 `demo_external_refs`) so the caller can
  later fetch by their own id. `source` here is the ingestion *transport* (url/path);
  `refs[].source` is the *integrator* (hltv/faceit/…) — keep the two distinct in code.
- Auth required (Stage 03). `path` intake is **gated to admin/owner only** (debug), never
  exposed to customers — fetching arbitrary server paths is dangerous.
- Create an `ingest_jobs` row, enqueue an arq job, return `job_id` immediately. The API
  never parses inline.
- Optional `webhook_url`: POST `{job_id, demo_id, status}` on completion/failure.

## 5.2 Worker job (arq, CPU-heavy)

Pipeline stages, updating `ingest_jobs.progress` as it goes:

1. **Acquire bytes**
   - `url`: stream-download with `httpx` (size cap, timeout). **SSRF guard** below.
   - `path`: read local file (admin/debug only).
2. **Decompress/extract** to a temp `.dem`:
   - `.dem` → use directly.
   - `.gz` → gzip stream decompress (old code already does zstd for one source; generalize).
   - `.zip` → extract the single `.dem` member (reject zips with many/huge members — zip-bomb guard).
   - `.rar` → **decide**: requires `unrar`/`patool` (non-free). Either install it in the
     image and support it, or return a clear "rar unsupported" error. Document the choice.
   - Detect by magic bytes, not just extension.
3. **Hash + dedup**: sha256 the raw `.dem`. If a `demos` row with that hash is `ready`,
   short-circuit: link the job to the existing demo, skip parsing (gap #6, idempotency).
   **Then attach `refs`**: upsert each `(source, external_id)` into `demo_external_refs`
   pointing at this demo. This is the key behavior for HLTV — re-submitting an already-parsed
   demo just tags it with the HLTV id, cheaply. Conflict handling: if a `(source,
   external_id)` already maps to a *different* demo, return that existing demo + a warning
   rather than reassigning (the unique key prevents silent reassignment).
4. **Classify (header probe) before the heavy parse** (Stage 11): determine GOTV vs POV,
   game version (CS2 — reject CSGO), map + `map_version`, tickrate, expected rounds. Reject
   unsupported demos *here*, before paying for a full parse.
5. **Archive the raw `.dem`** (cold tier, Stage 10): stream-compress with
   `zstd --ultra -22 --long=31` and upload to the cold archive; record `raw_storage_key`,
   `raw_codec`, `raw_bytes`. This is the true source of truth for future re-parses.
6. **Parse** with the awpy fork (port `process_demo_from_file` + `_player_props` list from
   `demo_processor.py`). Parsing releases the GIL (Rust), but post-processing is pandas-heavy
   → keep it on the worker, use `asyncio.to_thread`/process semaphore as the old code does.
   Handle the real-world cases (disconnects, OT/MR12 scoring, non-players) per Stage 11.
7. **Canonical store**: `Demo.compress(outpath=…)` → upload `canonical.zip` to the warm
   tier as `demos/{demo_id}/canonical.zip`.
8. **Build per-round payloads**: port `_process_single_round`, `_process_grenades`,
   `_create_utilities`, `parse_bomb_events`, etc. from `demo_processor.py` to emit the
   per-round payload schema from Stage 02. Upload each `round-{i}.bin`, write `demo_rounds`
   rows, and an `index.json`. **This replaces writing gzipped blobs into MySQL.** Apply the
   steam-id privacy toggle here if set (Stage 13).
9. **Metadata**: header (map, tick rate), round index, optional Steam player summaries.
   Port `_get_steam_player_data` but **fix the `verify=False`** (don't disable TLS) and make
   it optional/cached/failable.
10. **Finalize**: insert any `refs` into `demo_external_refs` for the new demo, set
   `demos.status='ready'`, `ready_at`, fire webhook (signed + retried, Stage 16). On any
   failure set `failed` + `error`, keep the temp cleanup (`finally: os.remove`) from old code.

Concurrency: bound parallel parses per worker (CPU count), reuse the per-round semaphore
pattern (`asyncio.Semaphore(15)`) for the I/O-bound payload uploads.

## 5.3 Security — download-link ingestion (gap #4, do not skip)

- **SSRF**: resolve the URL host; reject private/loopback/link-local ranges and cloud
  metadata IPs (169.254.169.254, etc.). Re-check after redirects (or disable redirects).
  Optional allowlist of known demo hosts (FACEIT, etc.).
- **Size**: cap streamed bytes (e.g. 500 MB raw / configurable); abort over-limit downloads.
- **Time**: hard timeout on download and on parse.
- **Content**: validate it decompresses to a real `.dem` (magic bytes) before parsing.
- **Temp hygiene**: always delete temp files (the old `finally` block is the right pattern).

## 5.4 "DB or compress?" — the answer

Both, by role (Stage 00 §3): `Demo.compress()` is the **canonical** cold store (the ~10 MB
zip), and the **per-round payloads** are the hot, viewer-facing derivative. Do **not** store
gzipped blobs in the DB anymore — store object keys. Per-round payloads are regenerable from
`canonical.zip` when `payload_version` changes, so you never re-parse the raw demo.

## Reuse from existing code

- `demoparser/demo_processor.py` → the entire parse/transform core (port nearly verbatim,
  redirecting outputs to object storage + the payload schema instead of MySQL inserts).
- `demoparser/demo_service.py` → job lifecycle/status transitions (move to arq + `ingest_jobs`).
- `demoparser/helpers.py` → `create_tick_dict`, `parse_bomb_events`, `create_kill_tick_dict`,
  grenade/utility helpers — reuse directly.
- `demoparser/post_processor.py` → **skip** (stats/heatmaps are out of scope).
- awpy `Demo.compress()` for the canonical zip.

## Acceptance criteria

- **Tests (required for Done):** the tests this phase needs are written and green in CI — see
  `TESTING.md` for stack/layout and its per-phase table for exactly what to cover.

- `POST /ingest` with a URL returns a `job_id` immediately; the worker produces a `ready`
  demo with `canonical.zip` + N per-round payloads + `index.json` in object storage and
  `demos`/`demo_rounds` rows.
- Re-ingesting the same demo (same sha256) does **not** re-parse; returns the existing demo
  and attaches any new `refs` (e.g. an HLTV id) to it.
- A demo ingested with `refs:[{source:'hltv',external_id:'X'}]` is afterwards retrievable via
  `GET /v1/demos/by-ref/hltv/X` (Stage 06).
- A private-IP / oversized / non-demo URL is rejected with a clear error, no parse attempted.
- `path` intake works for a local fixture in debug/admin mode and is refused for customers.
- rar handling behaves exactly as documented (supported or cleanly rejected).
