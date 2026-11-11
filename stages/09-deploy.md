# Stage 09 — Deploy

**Goal:** run the API, the worker pool, and the CDN-served viewer + radar assets in
production, with room to scale parsing independently of serving.

## 9.1 Topology

- **API** (uvicorn, N replicas behind a load balancer) — stateless, async, read-heavy.
- **Worker pool** (arq, M replicas) — CPU-heavy parsing; scale on queue depth, separate
  from the API so a parse spike never degrades serving.
- **Redis** — limits, response cache, arq queue. **Already running** dockerized on the
  owner's Hetzner server (same stack as Percona); reuse it (or a dedicated DB index).
- **Percona / MySQL 8** — metadata only; small, but back it up. **Already running**
  dockerized on Hetzner. The new service connects to it with its own `demoviewer` database
  and credentials (do not collide with the legacy `csstrats` schema). Local dev uses a
  throwaway Percona via `deploy/compose.dev.yml`.
- **Object store + CDN** — **bunny.net**. The new **`demos`** storage zone (geo-replicated
  LA/NY/Frankfurt) holds `canonical.zip` + per-round payloads, fronted by its Pull Zone for
  CDN delivery. Radar assets already live on the existing maps pull zone
  (`csstrats.b-cdn.net`). Serve `viewer.js` from a pull zone too. This bunny edge is where
  the "optimize the shit out of it" payoff lands — most reads never hit the origin.

## 9.2 The viewer & radar assets

- Build `viewer/dist/viewer.js` (UMD + ESM) and publish to a bunny pull zone with a
  versioned path (e.g. `/v1/viewer.js`) so embedded copies pin a version; offer a `latest`
  alias.
- Radar assets (mostly SVG, incl. multi-level maps) **already exist** on `csstrats.b-cdn.net`
  and are referenced by `map_metadata.image_path`; `/v1/maps` returns those URLs. Only
  upload new radars when adding a map.
- Set long-lived immutable caching on the bundle (content-hashed filename). Configure the
  `demos` pull zone cache rules so per-round payloads serve `immutable` + ETag.

### 9.2.1 bunny.net configuration

- **`demos` storage zone**: confirm geo-replication (LA / NY / Frankfurt) is on; create/verify
  its Pull Zone and note the CDN hostname used by `ObjectStore` read URLs.
- Store the storage-zone password (write AccessKey) and pull-zone host in secrets/env
  (`BUNNY_DEMOS_STORAGE_KEY`, `BUNNY_DEMOS_CDN_HOST`). Workers use the write key; the API
  only emits read URLs.
- Optionally enable bunny **Perma-Cache**/origin shielding so cold rounds are pulled once.

## 9.3 Config & secrets

- Per-env config via env vars (Stage 01): DB DSN, Redis URL, object-store creds, admin
  token, Steam key, size/limit caps, `PAYLOAD_VERSION`, CDN base URLs.
- Secrets in a manager (not in the image). Separate keys per environment.

## 9.4 CI/CD

- Build/test the API image and the viewer bundle; run `/security-review` and the acceptance
  checks from each stage in CI.
- Migrations run on deploy (gated). Blue/green or rolling for the API; workers can drain the
  queue and restart.

## 9.5 Scaling notes

- Parsing is the expensive, bursty part → autoscale workers on arq queue depth; the API
  scales on request load. They scale independently *because* they're separate processes.
- Serving is mostly CDN once warm; origin load is dominated by cold rounds + metadata.
- Tune the `aiomysql` pool (old code used max 50) and Redis connection counts to replica
  count — and leave headroom on the shared Percona instance for other apps in that stack.

## Reuse from existing code

- `demoparser/Dockerfile`, `demoparser/compose-example.yml` → container + compose baseline,
  extended with redis + object store + the worker service.

## Acceptance criteria

- **Tests (required for Done):** the tests this phase needs are written and green in CI — see
  `TESTING.md` for stack/layout and its per-phase table for exactly what to cover.

- API and workers deploy as independent, separately-scalable services.
- `viewer.js` and radar assets are served from the CDN with immutable caching and a pinned
  version path.
- A demo ingested in prod is viewable on an external test page via both direct and proxy
  modes.
- Workers autoscale on queue depth without affecting serving latency.
