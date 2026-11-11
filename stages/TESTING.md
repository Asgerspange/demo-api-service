# Testing Standard

**Mandatory for every phase.** A phase is **not Done** until the tests it requires are
written and green in CI (enforced by the Definition of Done in `CHECKLIST.md`). Each stage's
Acceptance criteria points here; the per-phase table below says what to cover.

## Stack & layout

- **Python:** `pytest` + `pytest-asyncio`; `httpx.AsyncClient` (ASGI transport) for the API;
  a disposable test MySQL (the `deploy/compose.dev.yml` Percona, or `testcontainers`) and a
  test Redis (or `fakeredis`); `respx` / `pytest-httpx` to mock all outbound HTTP (bunny
  Storage/CDN, Steam). Add these as a `dev` dependency group in `api/pyproject.toml`.
- **Layout:**
  ```
  api/tests/
    conftest.py          # fixtures: settings override, db pool, redis, fake ObjectStore, sample demo path
    unit/                # pure logic, no I/O
    integration/         # real test MySQL + Redis; bunny/Steam mocked
    e2e/                 # full flow through the ASGI app
    fixtures/            # tiny golden files, sample payloads
  ```
- **Viewer (JS):** `vitest` + `jsdom` for the worker decode/transforms and pure functions;
  `Playwright` for render correctness, visual snapshots, and mobile/touch.
- **Naming/markers:** `test_*.py`; mark `@pytest.mark.unit | integration | e2e | slow`.
- **Run:** `uv run pytest`. **CI:** `uv run pytest -m "not slow"` on every PR; full suite +
  the Stage 15 corpus on `main`.

## The four layers

- **Unit** — pure logic, no network/DB, fast: per-round payload builder, MR12/OT score logic,
  grenade/utility/bounce math, key hashing, rate-limit window math, zstd round-trip, SSRF
  host classification, payload-version negotiation.
- **Integration** — real test MySQL + Redis: migrations apply + `map_metadata` seed, repos,
  the auth dependency, the rate limiter, ingest job state machine. bunny + Steam mocked.
- **E2E** — drive the ASGI app end-to-end with bunny mocked: ingest `demo.dem` (path mode) →
  poll to `ready` → `GET /v1/demos/{id}` → fetch a round → assert the shape the viewer expects.
- **Golden / regression** (Stage 15) — the pinned demo corpus, golden parse outputs, and
  viewer visual snapshots; the CI gate on any parser/payload/renderer change.

## Rules

- **No real network** in unit/integration except the test MySQL/Redis — mock bunny (`respx`)
  and Steam. Never hit production bunny zones from tests.
- **Deterministic:** no real wall-clock or randomness in assertions; pin fixtures and seeds.
- **Every bug fix lands a failing-first regression test.** (First one to write: the `int32`
  `winner`/`reason` demo that crashed `create_round_df` → fold into the Stage 11 corpus.)
- **Security tests are required** wherever a stage flags one: SSRF (private/redirect/oversize),
  client-key origin-lock allow/deny, CDN token-auth 403s, zip-bomb / path-traversal extraction,
  cross-tenant `by-ref` 404.
- **Coverage:** target ≥ 80% on `api/app/` (the parse/serve core should be higher). Don't chase
  100% — prefer meaningful behavior tests over line-coverage padding.

## Per-phase: what to test

| Phase | Must-test (minimum) |
|---|---|
| 01 Scaffold | config fail-fast (missing prod secrets → exit 1); `/healthz`; `/readyz` red when a dep is down; worker boots |
| 02 Data & storage | migrations apply; `map_metadata` seeds 16 rows; repo CRUD; `ObjectStore` put/get/url (bunny mocked); a fixture round matches the `RoundLoader.worker.js` schema |
| 03 Auth & keys | key gen/hash/verify; origin-lock allow **and** deny (403); server-key+browser-origin → 400; rotation grace window; revocation within TTL; admin guard blocks unauth |
| 04 Rate limit & proxy | 101st client req → 429 + `Retry-After`; per-`X-End-User` buckets isolated; missing `X-End-User` → 400; `X-RateLimit-*` headers; reference proxy passes `/v1/**` + caching headers through |
| 05 Ingestion | extract `.gz`/`.zip`(bomb-guarded)/`.dem` by magic bytes; SSRF rejects private IP/redirect/oversize; sha256 dedup attaches refs without re-parse; `path` intake admin-only; zstd cold archive round-trips; job state transitions |
| 06 Serving | demo metadata + round index + `refs`; round bytes `immutable`+`ETag`, `If-None-Match`→304; `by-ref` resolves + cross-tenant 404; `/v1/maps` from seed; listing pagination; direct == proxy parity |
| 07 Viewer | worker decode → correct TypedArrays (vitest); bounded memory across many round switches; theme toggles; `destroy()` leaves no worker/listeners; render snapshots dust2/mirage/nuke (SVG) |
| 08 Perf/hardening | load test meets p99 target; SSRF re-audit; no `verify=False` anywhere; zip-bomb/path-traversal blocked; delete purges hot+warm+cold + rows |
| 09 Deploy | image builds (done); `compose.dev` smoke; CDN/cache headers preserved through the proxy |
| 10 Storage tiering | 3 artifacts written to 3 tiers; same demo stored once (dedup); cold raw `.dem` round-trips byte-identical; delete removes all tiers |
| 11 Real-world demos | corpus parses-or-rejects each case (GOTV/POV/128t/OT/disconnect/bots/knife/truncated); OT scoreline correct; player-slot stability across reconnect; the `int32` regression |
| 12 Map versioning | correct calibration version resolved; drift → `calibration_suspect` flag; unknown map → graceful state |
| 13 Access control | payload URL without/expired token → 403; guessable key blocked; bandwidth cap throttles; steam-id anonymize stable within a demo |
| 14 Reprocess/backfill | `payload_version` backfill from parquet; deep re-parse from cold raw; resumable after kill; verify-before-flip rejects bad batch |
| 15 Corpus/regression | the harness itself: golden diffs fail the build; viewer visual snapshots; add-a-reproducer flow works |
| 16 Multi-tenancy | bulk tenant doesn't starve another (fairness); idempotency key dedupes; webhook HMAC + retry/backoff; documented DR restore runs |
| 17 Viewer UX & compat | deep-link restores exact round+tick; touch/responsive; timers + killfeed; old `payload_version` still decodes against current API |
