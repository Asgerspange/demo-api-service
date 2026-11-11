-- Stage 02 — initial schema. MySQL 8 / Percona, InnoDB, utf8mb4, UTC timestamps.
-- The service uses its own `demoviewer` database (clean separation from legacy `csstrats`).
-- DB holds small queryable metadata + object-store pointers; the heavy bytes live in bunny.
-- Applied (once, in filename order) by app/storage/migrate.py.

-- Users are created ONLY by the owner (Stage 03). No public signup.
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

-- Map calibration + radar asset URLs. Seeded from map_metadata.sql (authoritative;
-- supersedes scales.js) by migration 002. selections drives multi-level maps
-- (nuke/vertigo/baggage). Reference data, seeded once.
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
