# Stage 00 — Architecture & Decisions

This is the orientation document. Read it before any other stage. It defines the
system shape, the key decisions, and **answers "am I missing anything?"** with the
gaps that were not in the original brief but must be handled.

---

## 1. System shape

```
                                  ┌──────────────────────────────┐
   Any website                    │        Owner API (Python)    │
 ┌───────────────┐  direct        │  FastAPI (async, uvicorn)    │
 │ <cs-viewer>   │───clientKey────▶│  ├─ /v1 serving (read)       │
 │ pure JS +     │                 │  ├─ ingestion intake         │
 │ web worker +  │                 │  ├─ admin (owner only)       │
 │ canvas        │   proxy         │  └─ auth + rate limit        │
 └──────┬────────┘──────┐          └───┬───────────┬──────────────┘
        │               │              │           │
        │        ┌──────▼───────┐      │           │
        │        │ Customer     │      │           │
        │        │ backend proxy│serverKey         │
        │        │ (their infra)│──────┘           │
        │        └──────────────┘                  │
        │                                          │
   radar SVG + viewer.js                 ┌─────────▼─────────┐   ┌──────────────┐
   from bunny CDN ◀─────────────────────│  Redis (limits,   │   │  Workers     │
                                         │  cache, job queue)│◀──│  (parse pool)│
                                         └─────────┬─────────┘   └──────┬───────┘
                                                   │                    │
                                         ┌─────────▼─────────┐   ┌──────▼────────────┐
                                         │  Percona/MySQL    │   │ bunny.net Storage │
                                         │  (meta,users,keys,│   │ `demos` zone      │
                                         │  jobs,map_metadata)   │ (LA/NY/FRA repl): │
                                         └───────────────────┘   │ parquet+payloads  │
                                                                 └───────────────────┘
```

Two processes share the codebase: the **API** (async, serving + intake, never
blocks on parsing) and the **worker pool** (CPU-heavy awpy parsing). They
communicate through a Redis-backed job queue. This is the single biggest change
from the old design, which polled MySQL on a timer inside one process.

## 2. Decided tech stack

| Concern | Choice | Why |
|---|---|---|
| API framework | FastAPI + uvicorn | Already a dependency; async; great for fan-out serving |
| Language runtime | Python 3.12 | Matches `demoparser/pyproject.toml` |
| Parser | awpy fork (`asgerspange/awpy`) → demoparser2 (Rust) | Already proven; releases GIL during parse |
| Job queue | **arq** (asyncio-native, Redis) | No separate broker; fits async API; lighter than Celery |
| Metadata DB | **MySQL 8 (Percona)** via `aiomysql` | Owner already runs Percona (dockerized on Hetzner); matches the old `demoparser` stack |
| Cache + limits + queue | **Redis** (existing) | Already running in the same Hetzner stack as Percona; covers rate limiting, response cache, arq broker |
| Object storage + CDN | **bunny.net Storage zones + Pull Zones** | Already in use (`csstrats.b-cdn.net` for maps); the new **`demos`** zone is geo-replicated (LA/NY/Frankfurt). Demos are ~10 MB each → object store, **not** DB longblobs |
| Viewer | Vanilla JS, Canvas 2D, inlined Web Worker, built to one file | Embeds anywhere; port columnar approach from `RoundLoader.worker.js` |
| Viewer distribution | CDN-served `viewer.js` (UMD + ESM) + Web Component wrapper | `<script>` tag OR `<cs-demoviewer>` element |

> **Infra is decided:** prod runs Percona (MySQL 8) + Redis dockerized together on the
> owner's Hetzner server. For local development we run a throwaway Percona + Redis via
> `deploy/compose.dev.yml` (Stage 01) so the agent/dev can connect and query directly —
> we do **not** develop against the production DB.

## 3. The storage decision (most important)

The old system stored **gzipped per-round JSON blobs in MySQL** — perfect for the
viewer's lazy per-round loading, terrible for storage cost and portability. The new
brief wants `Demo.compress()` → a zip of parquet-per-dataframe (~10 MB) — perfect for
cheap archival, but **not directly consumable by the viewer** (the browser can't cheaply
slice a parquet zip per round).

**Decision: keep both, with clear roles.**

- **Canonical store** = `Demo.compress()` parquet zip in the bunny.net **`demos`** storage
  zone (geo-replicated LA/NY/Frankfurt). One object per demo. This is the source of truth
  and what makes a demo "10 MB total".
- **Viewer payloads** = per-round, render-ready blobs (the columnar/JSON format the old
  `RoundLoader.worker.js` consumes), **derived** from the parse and stored as small
  per-round objects in the same `demos` zone (or Redis for hot demos), served immutably via
  the zone's pull-zone CDN.

So a parse produces: (1) one canonical parquet zip, (2) N small per-round payloads.
The per-round payloads are regenerable from the parquet zip if the format changes
(this is why we keep the parquet — re-derive without re-downloading/re-parsing the demo).

See Stage 02 for the exact payload schema and Stage 06 for how it's served.

## 4. The key & proxy model

- **Client key** (`pk_live_…`) — public, shipped in the browser. Useless without a
  matching **allowed-origin**: the API rejects it unless `Origin`/`Referer` is on the
  key's allowlist. Hard-capped at **100 requests/hour** per key (the brief's number).
- **Server key** (`sk_live_…`) — secret, never in a browser. Used **only** from the
  customer's backend proxy. The owner sets **per-user limits** for this key, attributed
  by an `X-End-User` identifier the proxy forwards.
- **Owner** — a single super-admin who creates users and issues/rotates keys via the
  admin interface. No public signup.

The viewer is agnostic: it points at a `apiBase` that is **either** the owner API
(direct, with a client key) **or** the customer's proxy (no secret in browser). Both must
expose the identical path contract (Stage 06 §"Request contract"). The proxy pattern and
reference implementations are in Stage 04.

## 5. Repo layout (target)

```
demoviewer/
├── stages/                 # this folder
├── api/                    # Python service (Stage 01)
│   ├── app/
│   │   ├── main.py         # FastAPI app factory
│   │   ├── config.py       # env config (port from demoparser/config.py)
│   │   ├── deps.py         # auth/ratelimit dependencies
│   │   ├── routers/        # serving, ingestion, admin
│   │   ├── auth/           # key issuance, verification, origin checks
│   │   ├── ratelimit/      # redis limiter
│   │   ├── ingest/         # download, extract, parse (port demo_processor.py)
│   │   ├── parsing/        # awpy wrapper + per-round payload builder
│   │   ├── storage/        # object store + DB repositories
│   │   └── worker.py       # arq worker entrypoint
│   ├── pyproject.toml      # port deps from demoparser/pyproject.toml
│   └── Dockerfile
├── viewer/                 # embeddable JS (Stage 07)
│   ├── src/                # renderer, worker, web component
│   ├── dist/               # built viewer.js (CDN artifact)
│   └── examples/           # drop-in HTML samples
└── deploy/                 # compose, infra (Stage 09)
```

## 6. "Am I missing anything?" — gaps the brief did not mention

These are real and each is folded into a stage. Skim them now.

1. **Per-round payloads ≠ parquet zip.** You need a render-ready per-round format
   *in addition to* `dem.compress()`. (Stage 02/06) — already covered above.
2. **Object storage, not DB blobs.** 10 MB/demo in Postgres/MySQL will not scale and
   blocks cheap CDN serving. Use the **bunny.net `demos` storage zone** (geo-replicated
   LA/NY/Frankfurt) fronted by a pull zone; DB holds metadata + object keys only. (Stage 02)
3. **A real job queue + worker pool.** Parsing is CPU-bound and slow; it must not run in
   the API process. Replace the APScheduler-polls-MySQL design with arq + workers. (Stage 05)
4. **SSRF + abuse on download-link ingestion.** "Give me a URL and I'll fetch it" is a
   classic SSRF hole. Need URL allow/deny rules (block private IPs/metadata endpoints),
   max size, timeouts, content-type checks. (Stage 05 §Security)
5. **RAR is non-trivial.** zip/gzip are stdlib; **rar needs `unrar`/`patool`** (non-free
   codec) installed in the image, or document it as unsupported. Decide explicitly. (Stage 05)
6. **Demo de-duplication.** Hash the raw `.dem` (sha256); skip re-parsing identical demos.
   Saves money and gives idempotent ingestion. (Stage 02/05)
7. **Client keys are visible — they need origin locking + revocation,** not just a rate
   limit. A leaked client key with no domain lock is a free 100/hr to the world. (Stage 03)
8. **End-user attribution for server-key limits.** "Per-user limits" only works if the
   proxy tells us *which* end-user a request is for. Define the `X-End-User` header and
   what counts as a user. (Stage 04)
9. **Map assets already exist on bunny CDN.** Calibration lives in the **`map_metadata`
   table** (`map_metadata.sql` — supersedes `scales.js`): offset/scale/rotate/zoom, multi-
   level `selections` (nuke/vertigo/baggage), and `image_path` pointing at existing radar
   assets on `csstrats.b-cdn.net` — mostly **SVG**, a few legacy PNG/local. Expose via
   `/v1/maps`; the viewer must render SVG radars. (Stage 06/07)
10. **Web Workers + CORS.** An embedded viewer can't load a worker from a cross-origin URL
    without care. Inline the worker (Blob URL) or ship it same-origin with the bundle. (Stage 07)
11. **Immutability & caching.** Parsed demo data never changes → per-round payloads are
    immutable and should be served with long-lived `Cache-Control: immutable` + ETag, and
    fronted by CDN. This is most of your performance. (Stage 06/08)
12. **API + schema versioning.** Keep `/v1` and a `payload_version` so the viewer can
    evolve without breaking embedded copies on customer sites you don't control. (Stage 02/06)
13. **Job status + (optional) webhooks.** Ingestion is async; callers need a job id to poll
    and optionally a completion webhook. (Stage 05)
14. **Steam metadata is an external dependency.** The old parser fetched player summaries
    from Steam (and disabled TLS verify — fix that). Make it optional/cached. (Stage 05)
15. **Observability.** Structured logs (loguru is already used), parse-failure tracking,
    metrics (queue depth, parse time, 429 rate), and an error tracker. (Stage 08)
16. **Legal/abuse:** demos may be large; define max upload/download size, retention, and
    delete semantics (GDPR-style "delete my demo"). (Stage 02/08)

## 7. Out of scope (explicitly)

Heatmaps, statistics pages, AI chat/antistrat, 3D viewer, scoreboards as separate pages,
team/folder sharing UI. The old repo has all of these — **do not port them**. The viewer
shows positions, utility, bomb, weapon-fire, and basic round/player HUD only.
