-- Stage 14 — reprocessing/backfill orchestration state. A run targets a payload_version with a
-- mode (cheap re-derive from parquet | deep re-parse from raw); per-demo rows make it resumable
-- and idempotent (a restart continues from `pending`, never re-charges `done`).

CREATE TABLE backfill_runs (
  id                     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  target_payload_version INT NOT NULL,
  mode                   VARCHAR(8)  NOT NULL,                 -- 'cheap' | 'deep'
  status                 VARCHAR(16) NOT NULL DEFAULT 'running', -- running|done|failed
  total                  INT NOT NULL DEFAULT 0,
  created_at             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE backfill_demos (
  run_id   BIGINT UNSIGNED NOT NULL,
  demo_id  BIGINT UNSIGNED NOT NULL,
  state    VARCHAR(16) NOT NULL DEFAULT 'pending',             -- pending|done|failed|skipped
  error    TEXT,
  PRIMARY KEY (run_id, demo_id),
  KEY idx_run_state (run_id, state),
  CONSTRAINT fk_bf_run FOREIGN KEY (run_id) REFERENCES backfill_runs(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
