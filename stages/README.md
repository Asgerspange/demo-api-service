# CS2 2D Demoviewer — Build Stages

This folder breaks the project into self-contained, ordered stages. Each file is
both a **spec** and a **prompt**: it carries enough context, concrete tasks, and
acceptance criteria to be executed (by a human or an AI agent) on its own.

## What we are building

1. **A Python serving + ingestion API** (FastAPI, async) that parses CS2 demos and
   serves the data needed to drive a 2D viewer — fast, concurrent, cache-friendly.
2. **A single-file, embeddable, pure-JS 2D viewer** that drops onto *any* website,
   is customizable per site, talks to either our API directly or to the site's own
   backend proxy, and runs inside a small browser-memory budget.
3. **A key + user system**: only the owner can create users; each user gets a
   public **client key** (rate-limited, domain-locked) and a secret **server key**
   (used from their backend, with owner-configurable per-end-user limits).

> Scope guardrail: the viewer is **purely a 2D playback viewer**. No heatmaps,
> no statistics dashboards, no 3D. Those existed in the old app and are out of scope.

## Stage index

| # | Stage | Output |
|---|-------|--------|
| [00](00-architecture.md) | Architecture & decisions | System design, the "what's missing" answers, repo layout |
| [01](01-project-scaffold.md) | Project scaffold | FastAPI skeleton, config, Docker, Redis, deps |
| [02](02-data-model-and-storage.md) | Data model & storage | DB schema, object storage, canonical parquet store + per-round payload format |
| [03](03-auth-and-keys.md) | Auth, keys & admin | Client/server keys, owner-only user creation, key issuance/rotation |
| [04](04-rate-limiting-and-proxy.md) | Rate limiting & proxy contract | Redis limits, per-end-user limits, the proxy pattern + reference proxies |
| [05](05-ingestion-pipeline.md) | Ingestion pipeline | Download/path intake, SSRF guards, worker queue, awpy parse, compress storage |
| [06](06-serving-api.md) | Serving API | Versioned endpoints, per-round lazy payloads, caching/ETag, map/scale data |
| [07](07-embeddable-viewer.md) | Embeddable viewer | Single-file JS, init/config API, worker decode, canvas renderer, theming |
| [08](08-perf-hardening-observability.md) | Perf, hardening & observability | CDN, load tests, memory budget, security review, metrics |
| [09](09-deploy.md) | Deploy | Infra, CDN for viewer + radars, worker scaling |
| [10](10-storage-tiering-and-archival.md) | Storage tiering & archival | 3-tier storage; compressed raw `.dem` for reparse; cost optimization |
| [11](11-real-world-demo-handling.md) | Real-world demo handling | POV/GOTV, MR12/OT scoring, disconnects, corrupt demos, game scope |
| [12](12-map-versioning-and-calibration.md) | Map versioning & calibration | Per-map versions, drift detection, recalibration, unknown-map fallback |
| [13](13-content-access-control.md) | Content access control & anti-abuse | CDN token URLs (close the scrape hole), bandwidth caps, steam-id privacy |
| [14](14-reprocessing-and-backfill.md) | Reprocessing & backfill | Re-derive from parquet / re-parse from raw; `payload_version` migration |
| [15](15-test-corpus-and-regression.md) | Test corpus & regression | Pinned demo corpus, golden parse outputs, visual regression, CI gate |
| [16](16-multitenancy-and-hardening.md) | Multi-tenancy & hardening | Queue fairness/priority, idempotency, signed webhooks, DR, status/staging |
| [17](17-viewer-ux-and-compat.md) | Viewer UX & compatibility | Deep-links, mobile/touch, timers/killfeed, i18n, version pinning |

**Stages 00–09** are the core build (MVP path). **Stages 10–17** harden it for untrusted
reality — messy demos, untrusted CDN consumers, Valve changing the game, and embeds you can't
update. Several extend earlier stages (noted inline); do 00–09 first, then layer 10–17.

## How to use

Work top to bottom. Stages 02–04 can be developed in parallel once 01 lands.
Each stage lists **Reuse from existing code** — port the proven logic from the
old Laravel/Vue/`demoparser` projects rather than rewriting from scratch.

## Testing is mandatory

**Every stage ships tests.** A phase is **not Done** until the tests it requires are written
and green in CI. See **[TESTING.md](TESTING.md)** for the stack, layout, the four test layers,
the coverage gate, and a per-phase "what to test" table. Per-phase completion gates live in
**[CHECKLIST.md](CHECKLIST.md)** — an agent ticks each box as a phase lands. Every bug fix
lands a failing-first regression test.

## Reference material in this repo (read-only, do not modify)

- `demoparser/` — old scheduler-based parser. Port the parsing/concurrency logic.
- `demoparser2/` — Rust parser that awpy depends on (the engine).
- `awpy.readthedocs.io/` — awpy docs; `Demo.compress()` is the canonical store format.
- `DemoController.php`, `CacheService.php`, `MapController.php` — old serving layer.
- `Demo/2D/`, `RoundLoader.worker.js`, `scales.js`, `useApi.ts` — old viewer; port the
  columnar/worker/render approach into the new vanilla-JS viewer.
- `tables_from_laravel.md` — current MySQL schema for the demo tables.
- `map_metadata.sql` — **authoritative** map calibration + bunny CDN radar URLs (mostly SVG
  on `csstrats.b-cdn.net`); supersedes `scales.js`. Seed it into the new DB (Stage 02).
- Storage target: bunny.net **`demos`** storage zone (geo-replicated LA/NY/Frankfurt) for
  parquet `canonical.zip` + per-round payloads (Stage 02 / 09).
