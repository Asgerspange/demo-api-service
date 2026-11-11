# Releasing on the server (Coolify · api.csstrats.dk)

Step-by-step to put the demoviewer API into production. `api` is a **Coolify** app (Build Pack:
Dockerfile, built from the repo's root `Dockerfile`); Coolify's built-in Traefik terminates TLS
and routes **`api.csstrats.dk`** to it. `migrate` and `worker` run as Docker Compose on the box.

```
            TLS (Coolify-managed)
  Internet ───────────────► Traefik ───────────────► api ×N (Coolify app) ──► Percona/Redis
   (api.csstrats.dk)      (Coolify)                  worker ×M (compose) ──► bunny.net
```

## 0. Prerequisites (on the box)

- Docker + Docker Compose v2.
- **Coolify**, with this repo added as an app: Build Pack **Dockerfile**, Base Directory `/`,
  Dockerfile Location `/Dockerfile`, Ports Exposes `8000`, no Port Mappings (Traefik reaches the
  container over Coolify's internal network — don't publish a host port), domain
  `https://api.csstrats.dk`.
- DNS: an **A/AAAA record for `api.csstrats.dk`** pointing at the server's public IP.
- Reachable **Percona/MySQL 8** (own `demoviewer` database + user) and **Redis** (demoviewer uses
  logical db 3) — these are the existing shared services.
- A **bunny.net** account with the zones from `deploy/.env.prod.example` (demos Pull Zone + cold
  archive). The worker image needs `bsdtar` for RAR/7z — it's baked into the image (Stage 18).

## 1. Get the code + configure secrets

```bash
git clone <repo> /opt/demoviewer && cd /opt/demoviewer
cp deploy/.env.prod.example deploy/.env.prod
$EDITOR deploy/.env.prod        # DB_*, REDIS_URL, BUNNY_* keys, a real ADMIN_TOKEN
```

`APP_ENV=production` makes the app **fail fast** at boot if the bunny keys or a real `ADMIN_TOKEN`
are missing — so a misconfigured deploy never starts half-up. Keep `deploy/.env.prod` out of git
(it's already `.gitignore`d) and in your secret manager.

## 1a. Connect to the existing Percona + Redis (shared network + DB bootstrap)

Percona (`percona_db`) and Redis (`redis_cache`) run in a **separate** (Portainer) infra stack,
attached to the external `csstrats_default` Docker network. `compose.prod.yml` joins that network,
so demoviewer reaches them **by container name** — `DB_HOST=percona_db`, `REDIS_URL=redis://redis_cache:6379/3`
(already the defaults in `.env.prod.example`). Their `127.0.0.1:3306/6379` published ports are
host-loopback-only and can't be used from a container, which is why we share the network instead.

Confirm the network exists (created by the infra stack):

```bash
docker network ls | grep csstrats_default
```

demoviewer needs its **own** database + user — the `csstrats` MySQL user only has rights on the
`csstrats` DB. Create them once as root (matches `DB_NAME`/`DB_USER`/`DB_PASSWORD` in `.env.prod`):

```bash
docker exec -it percona_db mysql -uroot -p   # root pw = MYSQL_ROOT_PASSWORD from the infra stack
```
```sql
CREATE DATABASE demoviewer CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'demoviewer'@'%' IDENTIFIED WITH mysql_native_password BY 'PUT_DB_PASSWORD_HERE';
GRANT ALL PRIVILEGES ON demoviewer.* TO 'demoviewer'@'%';
FLUSH PRIVILEGES;
```

(`mysql_native_password` matches the infra Percona's `--default-authentication-plugin`. Redis needs
no setup — demoviewer namespaces itself on logical db 3.)

## 2. Migrate and start the worker

```bash
cd /opt/demoviewer
docker compose -f deploy/compose.prod.yml --env-file deploy/.env.prod up -d --build
```

The one-shot **`migrate`** service applies pending SQL migrations (idempotent) and must succeed
before `worker` starts (and before the `api` Coolify app below serves traffic on a fresh DB).
Verify:

```bash
docker compose -f deploy/compose.prod.yml ps           # migrate=exited(0), worker=healthy
```

Scale the worker on queue depth any time:

```bash
docker compose -f deploy/compose.prod.yml --env-file deploy/.env.prod up -d --scale worker=6
```

## 3. Deploy `api` on Coolify

Add this repo as a Coolify app with:

- **Build Pack:** Dockerfile — **Base Directory:** `/` — **Dockerfile Location:** `/Dockerfile`
- **Ports Exposes:** `8000` — **Port Mappings:** none (Traefik reaches the container over
  Coolify's internal network; publishing a host port isn't needed and may collide with anything
  else already bound to it on the box)
- **Domain:** `https://api.csstrats.dk`
- **Watch Paths:** `api/**`, `Dockerfile` (skip redeploys for unrelated `viewer/`/`demoparser/` changes)
- Env vars: same keys as `deploy/.env.prod.example`
- Optional: a **pre-deployment command** of `python scripts/migrate.py` so migrations also run
  automatically on every Coolify deploy, not just via step 2 above.

Coolify's built-in Traefik terminates TLS for the domain and passes `Content-Encoding`/`ETag`/
`Cache-Control` through untouched, so immutable round payloads stay cacheable end-to-end. Deploy,
then smoke-test through TLS:

```bash
curl -fsS https://api.csstrats.dk/healthz              # {"status":"ok","api_version":"v1"}
```

## 4. Publish the viewer bundle to the demos CDN

Build + upload the bundle to the **root of the hot demos zone**, so embeds load it from the demos
CDN. The script sources `deploy/.env.prod` for the demos-zone creds:

```bash
cd viewer && npm ci && cd ..
./deploy/publish_viewer.sh
# → https://<BUNNY_DEMOS_CDN_HOST>/viewer.js   (embed this)
```

It's cached `public, max-age=300`, so a re-publish rolls forward within ~5 min (purge the demos Pull
Zone for an instant update). Embeds use `<script src="https://<demos-cdn>/viewer.js"></script>` — see
[../viewer/README.md](../viewer/README.md).

## 5. Onboard a customer (owner-only)

Creating tenants and issuing API keys is an **owner operation**, gated by `ADMIN_TOKEN` and kept off
the public API. Use the **owner dashboard** — a single token-prompted page — rather than scripting it:

```
https://api.csstrats.dk/admin/        (enter your ADMIN_TOKEN in-page)
```

From there: create a tenant, then issue a **client key** (origin-locked, embedded in the customer's
page) and/or a **server key** (proxy mode / backend ingestion). Each raw key is shown **once** — copy
it then. Hand the key to the integrator, who follows [VIEWER.md](../viewer/README.md) (embed) and
[API.md](API.md) (ingest + serving). The owner/admin surface is operator-only and is intentionally
absent from the public docs.

## 6. Operate

- **Health:** `GET /healthz` (liveness), `GET /readyz` (DB+Redis). Point uptime checks at these.
- **Metrics:** `GET /metrics` (Prometheus) — request/latency, 429 rate, queue depth, parse time.
- **Rollout:** redeploying the Coolify app drains to healthy replicas; `docker compose … up -d
  --build` re-rolls `worker` (finishes the current job, then restarts). Migrations run via the
  gated `migrate` one-shot (or the Coolify pre-deployment command, if set).
- **DR / backups / secrets rotation:** [DR.md](DR.md). **Webhooks:** [WEBHOOKS.md](WEBHOOKS.md).
  **Deprecation policy:** [DEPRECATION.md](DEPRECATION.md).
