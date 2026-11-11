# Stage 01 — Project Scaffold

**Goal:** stand up the Python API skeleton, configuration, and infra dependencies so
every later stage has a place to land. Nothing parses or serves real data yet — this is
the chassis.

## Context

The old `demoparser/` is a single-process APScheduler loop, not an API. We are building a
proper FastAPI service split into two runtimes that share one codebase: the **API** and the
**arq worker**. Reuse the config dataclass pattern from `demoparser/config.py`.

## Tasks

1. **Create `api/`** with the layout from Stage 00 §5. Use `pyproject.toml` ported from
   `demoparser/pyproject.toml` (FastAPI, uvicorn, loguru, orjson, pyarrow, zstandard,
   the awpy fork). Add: `arq`, `redis`, `aiomysql` (Percona/MySQL 8 — same driver the old
   `demoparser` uses), `httpx` (used both for downloads and as the bunny.net Storage API
   client — no S3 SDK needed), `pydantic-settings`.

2. **App factory** `app/main.py`: `create_app()` returning a FastAPI instance with
   - ORJSONResponse as default response class,
   - CORS middleware (origins configured per-key at request time, not globally — see Stage 03),
   - a `/healthz` (liveness) and `/readyz` (checks Redis + DB + object store) endpoint,
   - routers mounted under `/v1` (serving), `/ingest`, `/admin` (registered in later stages as stubs now).

3. **Config** `app/config.py`: `pydantic-settings` `Settings` loading from env. Cover:
   DB DSN, Redis URL, bunny `demos` storage-zone key + pull-zone CDN host
   (`BUNNY_DEMOS_STORAGE_KEY`, `BUNNY_DEMOS_CDN_HOST`), owner admin credential/secret,
   Steam API key (optional), max demo size, allowed-download settings, `PAYLOAD_VERSION`,
   `API_VERSION`. Keep a `.env.example`. Port the debug-mode idea from `demoparser/config.py`
   (a single local `.dem` path for development).

4. **Connection lifecycles**: async startup/shutdown for the `aiomysql` pool (port the
   pooling approach from `demoparser/demo_service.py`'s `get_pool`), a Redis client, and the
   bunny.net `ObjectStore` (httpx) client. Expose them via FastAPI dependencies in
   `app/deps.py`.

5. **Worker entrypoint** `app/worker.py`: an arq `WorkerSettings` with Redis connection and
   an empty `functions=[]` list (jobs added in Stage 05). Confirm `arq app.worker.WorkerSettings`
   boots and connects to Redis.

6. **Dockerization**: a multi-stage `Dockerfile` (build wheels, slim runtime). Two commands:
   `uvicorn app.main:app` and `arq app.worker.WorkerSettings`. Provide
   **`deploy/compose.dev.yml`** for local development, wiring api + worker + a **local
   Percona (MySQL 8)** + **Redis** — mirroring the prod stack so the dev/agent can connect
   and query directly (expose MySQL on a host port, e.g. 3307, with throwaway creds in
   `.env.example`). Object storage stays remote (a bunny dev zone/prefix) — no local S3
   needed. Port ideas from `demoparser/Dockerfile` and `demoparser/compose-example.yml`.

7. **Logging**: configure loguru once (structured, JSON in prod) and a request-id middleware.

## Reuse from existing code

- `demoparser/config.py` → config dataclass/env pattern (upgrade to pydantic-settings).
- `demoparser/demo_service.py` `get_pool()` → async DB pool lifecycle.
- `demoparser/Dockerfile`, `demoparser/compose-example.yml` → container baseline.
- `demoparser/pyproject.toml` → dependency set + the awpy git source pin.

## Acceptance criteria

- **Tests (required for Done):** the tests this phase needs are written and green in CI — see
  `TESTING.md` for stack/layout and its per-phase table for exactly what to cover.

- `docker compose -f deploy/compose.dev.yml up` brings up api + worker + Percona + Redis,
  with MySQL reachable from the host (e.g. `mysql -h127.0.0.1 -P3307`).
- `GET /healthz` returns 200; `GET /readyz` returns 200 only when all deps are reachable.
- `arq app.worker.WorkerSettings` starts and idles without error.
- Config fails fast with a clear message when a required env var is missing.
