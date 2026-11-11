-- Stage 16 — multi-tenancy, fairness & webhook hardening.
--
-- `tier` routes a tenant's ingest jobs to a priority lane (enterprise > standard > free); the
-- live lanes all outrank the backfill lane. `webhook_secret` is the per-user HMAC key used to
-- sign outbound webhooks (NULL until first issued; rotatable from /admin). Idempotency keys make
-- a client retry of POST /ingest return the SAME job instead of a duplicate. The dead-letter table
-- captures webhook deliveries that exhausted their retry budget so they're never silently lost.

ALTER TABLE users
  ADD COLUMN tier VARCHAR(16) NOT NULL DEFAULT 'standard' AFTER status,  -- enterprise|standard|free
  ADD COLUMN webhook_secret CHAR(64) NULL AFTER tier;                    -- per-user HMAC signing key

-- (user_id, idempotency_key) → the job created the first time that key was seen. A second POST
-- with the same key returns the same job_id rather than enqueuing another parse (gap #6 / §16.2).
CREATE TABLE ingest_idempotency (
  user_id         BIGINT UNSIGNED NOT NULL,
  idempotency_key VARCHAR(255) NOT NULL,
  job_id          CHAR(36) NOT NULL,
  created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id, idempotency_key),
  CONSTRAINT fk_idem_job FOREIGN KEY (job_id) REFERENCES ingest_jobs(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Webhook deliveries that exhausted the retry budget (§16.2). Kept for operator visibility +
-- manual replay; never silently dropped.
CREATE TABLE webhook_deadletter (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id     BIGINT UNSIGNED,
  job_id      CHAR(36),
  url         VARCHAR(512) NOT NULL,
  payload     JSON NOT NULL,
  attempts    INT NOT NULL,
  last_error  TEXT,
  created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_dl_user (user_id),
  KEY idx_dl_job (job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
