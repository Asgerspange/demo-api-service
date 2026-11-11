-- Stage 19 — cross-tenant dedup access.
--
-- Demos dedup globally by content hash (demos.sha256 is UNIQUE — one parse per unique demo).
-- But serving gated reads on the single demos.owner_user_id, so when a second tenant ingested
-- already-known content the pipeline attached their ref to the existing row without giving them
-- access — the demo was invisible to them (by-ref → 404). `demo_access` makes ownership
-- many-to-many: every tenant that ingests a demo (originally or via a dedup hit) is granted access,
-- and serving checks this table instead of owner_user_id. owner_user_id stays as the *creator*
-- (retained for delete/attribution). Deleting a demo cascades its grants.

CREATE TABLE demo_access (
  demo_id     BIGINT UNSIGNED NOT NULL,
  user_id     BIGINT UNSIGNED NOT NULL,
  granted_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (demo_id, user_id),
  KEY idx_access_user (user_id),
  CONSTRAINT fk_access_demo FOREIGN KEY (demo_id) REFERENCES demos(id) ON DELETE CASCADE,
  CONSTRAINT fk_access_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Backfill: every existing demo is accessible to its current owner, so nothing regresses.
INSERT INTO demo_access (demo_id, user_id)
  SELECT id, owner_user_id FROM demos;
