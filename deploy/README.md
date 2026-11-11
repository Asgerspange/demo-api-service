# Deploy (Stage 09)

The service runs as **two independently-scalable processes from one image** plus the
CDN-served viewer bundle. Redis, Percona, and bunny.net already exist on the owner's
infrastructure — the app connects to them via env.

```
                 ┌────────────┐         ┌──────────────────────────┐
   browsers ───► │ bunny CDN  │ ◄────── │ demos Pull Zone (payloads,│
   (viewer.js,   │ (edge)     │         │  canonical.zip, viewer.js)│
    radars,      └─────┬──────┘         └──────────────────────────┘
    payloads)          │ cache miss (cold)        ▲ write (workers)
                       ▼                           │
   /v1 reads ──► [ Coolify / Traefik ] ──► api (uvicorn ×N)  ──► Percona + Redis
   /ingest    ───────────────────────────────┘            ▲
                                              worker (arq ×M) ─┘  (parses, writes bunny)
```

- **api** — stateless, async, read-heavy. Scales on request load.
- **worker** — CPU-heavy parsing. Scales on **arq queue depth**, separate from the api so a
  parse spike never degrades serving.
- **Redis / Percona / bunny** — external, shared (demoviewer isolated on Redis db 3 and its own
  `demoviewer` MySQL database). Serving is mostly CDN once warm; origin load is cold rounds +
  metadata only.

## Deploy

**Full step-by-step server release runbook: [RELEASE.md](RELEASE.md)** (Coolify app setup for
`api.csstrats.dk`, viewer publish, smoke tests).

`api` is deployed as a **Coolify** app (Build Pack: Dockerfile, the repo's root `Dockerfile`,
port `8000`). Coolify's built-in Traefik terminates TLS for `api.csstrats.dk`, routes to the
container, and passes `Content-Encoding`/`ETag`/`Cache-Control` through untouched (no re-gzip) so
immutable round payloads stay cacheable end-to-end. No reverse proxy config lives in this repo.

`migrate` and `worker` still run via Compose:

```bash
cp deploy/.env.prod.example deploy/.env.prod        # fill in DB/Redis/bunny secrets + ADMIN_TOKEN
docker compose -f deploy/compose.prod.yml --env-file deploy/.env.prod up -d --build
```

The `migrate` one-shot applies pending migrations (idempotent) and must succeed before `worker`
starts. Scale workers on queue depth:

```bash
docker compose -f deploy/compose.prod.yml --env-file deploy/.env.prod up -d --scale worker=6
```

## Documentation

| Doc | For |
|---|---|
| [RELEASE.md](RELEASE.md) | Releasing on the server (Coolify · api.csstrats.dk) |
| [API.md](API.md) | Public HTTP API — ingest + serving (integrators) |
| [../viewer/README.md](../viewer/README.md) | Embeddable viewer bundle usage |
| [WEBHOOKS.md](WEBHOOKS.md) | Webhook signature scheme + delivery |
| [DEPRECATION.md](DEPRECATION.md) | API + payload version support policy |
| [DR.md](DR.md) | Backups, restore, rebuild-from-storage, secrets rotation |
| [STORAGE.md](STORAGE.md) | Storage tiering + per-demo cost |

### Autoscaling workers on queue depth

`worker` replicas are stateless arq consumers — scale them on the **`arq:queue` length** in
Redis (the metric your orchestrator polls). On plain compose, bump `--scale worker=N` from a
cron/alert; on k8s/Nomad, drive an HPA/autoscaler off the queue-depth gauge. Serving latency is
unaffected because the api tier is a separate deployment.

### Priority lanes & per-tenant fairness (Stage 16 §16.1)

Ingest jobs are routed to a queue by tenant **tier** (set per tenant from the owner dashboard →
`enterprise` > `standard` > `free`), and backfill runs on a strictly-lowest lane. Each worker pool
drains ONE lane via `WORKER_QUEUE`:

| Lane | Queue | `WORKER_QUEUE` |
|---|---|---|
| standard (default) | `arq:queue` | *(empty)* |
| enterprise | `arq:queue:enterprise` | `arq:queue:enterprise` |
| free | `arq:queue:free` | `arq:queue:free` |
| backfill | `arq:queue:backfill` | `arq:queue:backfill` |

Give higher tiers more replicas. The baseline single `worker` (no `WORKER_QUEUE`) drains the
standard lane, so the default deployment needs no extra config. **Within** a lane, a per-tenant
concurrency cap (`INGEST_TENANT_MAX_INFLIGHT`) bounds how many of a tenant's parses run at once: a
worker that picks up a job for an at-capacity tenant re-enqueues it with a short defer and frees its
slot, so one tenant's 500-demo batch can never stall another tenant's single demo. **Backpressure**
(`INGEST_QUEUE_DEPTH_CEILING > 0`) sheds new ingests with `429 + Retry-After` above the ceiling.

## bunny.net configuration (§9.2.1)

1. **`demos` storage zone** — enable geo-replication (LA / NY / Frankfurt). Create/verify its
   **Pull Zone**; put its hostname in `BUNNY_DEMOS_CDN_HOST` (the API emits read URLs against it).
   Workers write with `BUNNY_DEMOS_STORAGE_KEY`; the API never holds the write key.
2. **Cold archive zone** — `BUNNY_ARCHIVE_ZONE` + `BUNNY_ARCHIVE_STORAGE_KEY` for the compressed
   raw `.dem` (never served; read back only for re-parse/backfill).
3. **Pull Zone cache rules** — per-round payloads are immutable: serve `public, max-age=31536000,
   immutable` + honor `ETag`. Optionally enable **Perma-Cache**/origin-shield so cold rounds are
   pulled once.
4. **Viewer + radars** — radars already live on `csstrats.b-cdn.net` (referenced by
   `map_metadata.image_path`; only upload when adding a map). Publish the viewer bundle:

   ```bash
   BUNNY_VIEWER_STORAGE_KEY=... BUNNY_VIEWER_ZONE=demoviewer-assets ./deploy/publish_viewer.sh
   ```

   → `https://<viewer-pull-zone>/viewer/v<version>/viewer.js` (pin this in embeds) plus a
   `/viewer/latest/` alias. Set the Pull Zone to cache `/viewer/v*/` immutable and `/viewer/latest/`
   short-TTL.

## Config & secrets (§9.3)

All config is env (`deploy/.env.prod`); keep the filled file in a secret manager, **never in the
image or git**. `APP_ENV=production` makes the app fail fast if the bunny keys or a real
`ADMIN_TOKEN` are missing. Use separate keys per environment.

## CI/CD (§9.4)

`.github/workflows/ci.yml` runs on every push/PR: API tests (`pytest -m "not slow"` against a
throwaway Percona; Redis faked), viewer tests + bundle build, and an image build. Migrations run
via the gated `migrate` one-shot on deploy. Roll the api (the proxy drains to healthy replicas);
workers finish their current job and restart.

## Tuning (§9.5)

- `aiomysql` pool (`app/db.py`, maxsize 10/replica) and Redis connections scale with replica
  count — leave headroom on the shared Percona/Redis for the other apps in that stack.
- Bound parses per worker via `INGEST_ROUND_UPLOAD_CONCURRENCY` and the worker's `max_jobs`
  (`app/worker.py`), and CPU via the compose `cpus` limit.
