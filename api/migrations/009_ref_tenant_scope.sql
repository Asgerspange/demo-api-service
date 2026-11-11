-- Stage 19 — tenant-scope external refs.
--
-- demo_external_refs was global (source, external_id → demo). Once demos dedup across tenants
-- (demo_access), a shared demo's refs were visible to every tenant that could read it — leaking
-- e.g. one customer's Steam share codes to another. Refs now belong to the tenant that attached
-- them: (source, external_id) resolves and lists only within the requesting tenant, so the shared
-- demo *bytes* stay deduped but its refs stay private per tenant.

ALTER TABLE demo_external_refs
  ADD COLUMN user_id BIGINT UNSIGNED NULL AFTER demo_id;

-- Backfill: an existing ref belongs to the tenant that owns its demo.
UPDATE demo_external_refs r JOIN demos d ON d.id = r.demo_id
  SET r.user_id = d.owner_user_id;

-- Uniqueness moves to (demo_id, source, external_id, user_id): two tenants may attach the same
-- match id to the same shared demo (one row each). Add a tenant-scoped resolve index.
ALTER TABLE demo_external_refs
  MODIFY user_id BIGINT UNSIGNED NOT NULL,
  DROP KEY uq_demo_source_ref,
  ADD UNIQUE KEY uq_demo_source_ref_user (demo_id, source, external_id, user_id),
  ADD KEY idx_user_source_ref (user_id, source, external_id),
  ADD CONSTRAINT fk_ref_user FOREIGN KEY (user_id) REFERENCES users(id);
