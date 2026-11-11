# Stage 02 — Data Model & Storage

**Goal:** define the database schema, the object-storage layout, the canonical
parquet-zip store, and the **per-round viewer payload format**. This stage is the
contract every other stage reads/writes against.

## Context

Old storage (see `tables_from_laravel.md`) put gzipped per-round JSON in
`demo_rounds.frame_data` (longblob) and stat blobs in JSON columns inside MySQL. That
couples cheap CDN serving and storage cost to the DB. We split responsibilities:

- **DB** = small, queryable metadata + pointers (Postgres recommended).
- **Object store** = the heavy bytes (canonical parquet zip + per-round payloads).

## 2.1 Database schema (MySQL 8 / Percona)

The service uses its **own database** (e.g. `demoviewer`), not the legacy `csstrats`
schema — clean separation, while seeding `map_metadata` from `map_metadata.sql`. `aiomysql`,
`utf8mb4`, InnoDB. MySQL has no array type → arrays go in `json`; timestamps are UTC.

```sql
-- Users created ONLY by the owner (Stage 03). No public signup.
CREATE TABLE users (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  email         VARCHAR(255) NOT NULL UNIQUE,
  display_name  VARCHAR(255),
  status        VARCHAR(16) NOT NULL DEFAULT 'active',   -- active|suspended
  created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE api_keys (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id         BIGINT UNSIGNED NOT NULL,
  kind            VARCHAR(8)  NOT NULL,                   -- 'client' | 'server'
  prefix          VARCHAR(16) NOT NULL,                   -- 'pk_live' | 'sk_live' (display)
  key_hash        CHAR(64)    NOT NULL,                   -- sha256 (or argon2) of secret; never raw
  last4           CHAR(4)     NOT NULL,                   -- for display in admin
  allowed_origins JSON        NOT NULL,                   -- client keys: ["https://*.site.com"]
  rate_per_hour   INT,                                    -- client default 100; server: per-user cap
  status          VARCHAR(16) NOT NULL DEFAULT 'active',  -- active|revoked
  created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  revoked_at      TIMESTAMP NULL,
  KEY idx_key_hash (key_hash),
  CONSTRAINT fk_keys_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE demos (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  owner_user_id   BIGINT UNSIGNED NOT NULL,
  sha256          CHAR(64) NOT NULL,                      -- raw .dem hash for dedup
  map             VARCHAR(64) NOT NULL,
  name            VARCHAR(255) NOT NULL,
  status          VARCHAR(16) NOT NULL,                   -- queued|parsing|ready|failed
  payload_version INT NOT NULL,                           -- format version of per-round payloads
  round_count     INT,
  duration_ticks  INT,
  storage_key     VARCHAR(512),                           -- object key of canonical parquet zip
  meta            JSON,                                   -- header, player summaries (Steam), etc.
  error           TEXT,
  -- raw .dem archival + map versioning + retention; detailed in Stages 10 & 12
  raw_storage_key VARCHAR(512),                           -- cold archive key of compressed .dem
  raw_codec       VARCHAR(16),                            -- 'zstd'
  raw_bytes       BIGINT,                                 -- compressed size (cost tracking)
  retention_tier  VARCHAR(16) NOT NULL DEFAULT 'standard',-- standard|archive|ephemeral
  map_version     VARCHAR(64),                            -- workshop id / CRC if available
  created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ready_at        TIMESTAMP NULL,
  UNIQUE KEY uq_sha256 (sha256),                          -- dedup: one parse per unique demo
  KEY idx_owner (owner_user_id),
  CONSTRAINT fk_demos_user FOREIGN KEY (owner_user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE demo_rounds (
  demo_id      BIGINT UNSIGNED NOT NULL,
  round_index  INT NOT NULL,
  storage_key  VARCHAR(512) NOT NULL,                     -- object key of the per-round payload
  byte_size    INT NOT NULL,
  meta         JSON NOT NULL,                             -- lightweight round header (score, reason, ticks)
  PRIMARY KEY (demo_id, round_index),
  CONSTRAINT fk_rounds_demo FOREIGN KEY (demo_id) REFERENCES demos(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Dynamic external identifiers so any integrator can look a demo up by *their* id.
-- HLTV is just source='hltv'; the same mechanism serves faceit/esea/internal/etc.
-- One demo can carry refs from several sources; each (source, external_id) is globally
-- unique so a lookup is unambiguous. Survives dedup: when an identical demo (same sha256)
-- is re-ingested, we attach the new ref to the EXISTING demo rather than re-parsing.
CREATE TABLE demo_external_refs (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  demo_id     BIGINT UNSIGNED NOT NULL,
  source      VARCHAR(32)  NOT NULL,                    -- 'hltv' | 'faceit' | 'esea' | <slug>
  external_id VARCHAR(128) NOT NULL,                    -- the source's own id (e.g. HLTV match id)
  created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_source_ref (source, external_id),       -- unambiguous reverse lookup
  KEY idx_demo (demo_id),
  CONSTRAINT fk_ref_demo FOREIGN KEY (demo_id) REFERENCES demos(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Map calibration + radar asset URLs. Seed directly from map_metadata.sql (authoritative;
-- supersedes scales.js). image_path = existing bunny CDN radar (mostly SVG on
-- csstrats.b-cdn.net, a few legacy PNG/local). selections drives multi-level maps
-- (nuke/vertigo/baggage). Reference data, seeded once — schema matches map_metadata.sql.
CREATE TABLE map_metadata (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  map_id         INT NOT NULL,
  name           VARCHAR(255) NOT NULL UNIQUE,            -- e.g. 'de_mirage'
  display_name   VARCHAR(255),
  is_active_duty TINYINT(1) NOT NULL DEFAULT 0,
  pos_x          DOUBLE NOT NULL,
  pos_y          DOUBLE NOT NULL,
  scale          DOUBLE NOT NULL,
  rotate         DOUBLE,
  zoom           DOUBLE,
  selections     JSON,                                    -- [{name,altitude_max,altitude_min}]
  image_path     VARCHAR(255)                             -- radar URL (CDN SVG/PNG) or local path
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE ingest_jobs (
  id           CHAR(36) NOT NULL PRIMARY KEY,             -- uuid
  user_id      BIGINT UNSIGNED,
  source_type  VARCHAR(8)  NOT NULL,                      -- 'url' | 'path'
  source_ref   TEXT NOT NULL,                             -- url or local path
  demo_id      BIGINT UNSIGNED,
  status       VARCHAR(16) NOT NULL,                      -- queued|downloading|parsing|ready|failed
  progress     JSON,
  error        TEXT,
  webhook_url  VARCHAR(512),
  created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_status (status),
  CONSTRAINT fk_jobs_demo FOREIGN KEY (demo_id) REFERENCES demos(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Per-end-user usage counters for server-key limits live in Redis (Stage 04),
-- not here. Optionally mirror daily rollups into a usage table for billing.
```

Notes:
- `demos.sha256` UNIQUE gives **idempotent ingestion** and dedup (gap #6 in Stage 00).
- `demo_external_refs` lets HLTV (and any other integrator) query a demo by *their own* id
  via `GET /v1/demos/by-ref/{source}/{external_id}` (Stage 06). It is the "dynamic
  identifier" — add a new source by just inserting rows, no schema change.
- DB stores **object keys**, never the heavy bytes.
- `payload_version` lets the viewer evolve; bump it when the per-round format changes.
- Manage schema with a lightweight migration tool (e.g. raw `.sql` files applied in order, or
  `dbmate`/`yoyo`) — no heavy ORM. `map_metadata` is a data seed, not a migration target.

## 2.2 Object storage layout (bunny.net)

Two bunny.net Storage zones, each fronted by a Pull Zone (CDN):

- **`demos`** zone — new, **geo-replicated LA / NY / Frankfurt** (already created by the
  owner). Holds the canonical parquet zips **and** the per-round payloads.
- **maps** — existing assets already live on `csstrats.b-cdn.net` (the `image_path` URLs in
  `map_metadata`). Reused as-is; no new uploads needed unless adding maps.

Object keys inside the `demos` zone:
```
demos/{demo_id}/canonical.zip                      # Demo.compress() output (parquet per df)
demos/{demo_id}/v{payload_version}/round-{i}.bin   # per-round viewer payload
demos/{demo_id}/v{payload_version}/index.json      # round index + map + scale ref
```

bunny.net mechanics (Stage 05 writes, Stage 06/09 serve):
- **Write** via the Storage API: `PUT https://storage.bunnycdn.com/demos/{key}` with header
  `AccessKey: <storage-zone-password>` (upload to the main region; bunny replicates to
  LA/NY/FRA). Use an `httpx` client wrapper — bunny Storage is a plain HTTP API, not S3.
- **Read** via the zone's Pull Zone CDN hostname (e.g. `https://demos.b-cdn.net/{key}` or a
  custom domain). The serving API returns/relays these CDN URLs; it does not proxy bytes
  through itself for hot payloads.
- `canonical.zip` is the **warm** re-derivation cache (the "10 MB demo") — regenerate
  per-round payloads from it on a `payload_version` bump without re-parsing. It is **not** the
  ultimate source of truth: it only holds fields awpy extracted at parse time. The
  compressed **raw `.dem`** (cold tier) is the real source of truth for parser fixes / new
  fields. Full tiering — hot payloads / warm parquet / cold raw `.dem` — is **Stage 10**.
- Per-round objects get `Cache-Control: public, max-age=31536000, immutable` + ETag (set on
  upload via bunny headers / pull-zone cache rules).

Wrap bunny in an `ObjectStore` interface (Stage 2.4) so the rest of the code stays
provider-agnostic — only this adapter knows about bunny's API.

## 2.3 Per-round viewer payload format (the important one)

This is what the viewer's worker decodes. The old `RoundLoader.worker.js` already defines
the *target* shape — port it. Two viable encodings:

- **A. Gzipped JSON** (matches old system): a JSON object `{ ticks, meta, smokes, kills,
  grenades, ... }` keyed by tick, gzipped. Simplest; the worker turns it into columnar
  TypedArrays client-side (exactly as `RoundLoader.worker.js` does today).
- **B. Pre-columnarized binary** (recommended next step): do the columnar packing
  **server-side** at parse time and store TypedArray buffers directly (a small header +
  concatenated `Float32`/`Int16`/`Uint8` columns). The worker then does near-zero work and
  memory churn. This is the performance win — move the `RoundLoader.worker.js` transform
  to the server once.

**Plan: ship A first** (fast to port, identical to the proven old format), then add B as
`payload_version` 2 behind the same `/rounds/{i}` endpoint. The viewer negotiates via the
`index.json` `payload_version`.

Define the payload schema once, in code, shared by the parser (writer) and the viewer
(reader). Minimum per-round contents (from `RoundLoader.worker.js` + `demo_processor.py`):
- `ticks[t].players[]`: X, Y, yaw, health, armor_value, balance, flash_duration,
  has_defuser, has_helmet, is_walking, active_weapon_name, team_name, inventory (C4 bit),
  steamid, name.
- `ticks[t].bomb`: X, Y, planted_ticks.
- `ticks[t].weapon_fires[]`: player_steamid, player_X, player_Y, player_yaw, weapon.
- `ticks[t].grenades[]`: entity_id, grenade_type, X, Y, thrower_steamid.
- round `meta`: start/freeze_end/end/official_end ticks, winner, reason, scores, players.
- `smokes`, `infernos`, `kills` (round-scoped).

## 2.4 Storage repositories

Build a thin repository layer (`app/storage/`):
- `DemoRepo`, `RoundRepo`, `JobRepo`, `UserRepo`, `KeyRepo`, `MapRepo` — async DB access.
- `ObjectStore` — `put/get/url` adapter for the bunny.net `demos` storage zone (Storage API
  for writes, pull-zone CDN host for read URLs), with the key conventions above.
- Seed `map_metadata` once from `map_metadata.sql` (a migration/seed). `MapRepo.get(name)`
  feeds `/v1/maps` (Stage 06).
- Keep SQL explicit (no heavy ORM needed); port the async cursor style from
  `demoparser/demo_processor.py`.

## Reuse from existing code

- `tables_from_laravel.md` → field inventory for `demos`, `demo_rounds`, round `meta`.
- `map_metadata.sql` → seed the `map_metadata` table verbatim (authoritative calibration +
  bunny CDN radar URLs; `scales.js` is the older duplicate, keep only as a cross-check).
- `RoundLoader.worker.js` → exact per-round payload field set and the columnar target.
- `demo_processor.py` (`_process_single_round`, `_create_utilities`) → what goes into a
  round payload and how grenades/utilities are derived.
- awpy `Demo.compress()` (`awpy.readthedocs.io/.../_modules/awpy/demo.html`) → canonical zip.

## Acceptance criteria

- **Tests (required for Done):** the tests this phase needs are written and green in CI — see
  `TESTING.md` for stack/layout and its per-phase table for exactly what to cover.

- Migrations create all tables; `demos.sha256` uniqueness enforced; `map_metadata` seeded
  from `map_metadata.sql` (15 rows — id 15 was deleted upstream so the file holds 15, not 16;
  `name` unique).
- `ObjectStore` round-trips an object to the bunny `demos` zone and returns a working
  pull-zone CDN URL for it.
- A documented, code-shared schema for the per-round payload (v1 = gzipped JSON) exists and
  matches what `RoundLoader.worker.js` expects, verified by a fixture round.
