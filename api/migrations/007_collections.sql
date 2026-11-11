-- Stage 18 — multi-demo archives → collections, and shared external ids.
--
-- An HLTV match arrives as ONE archive holding several demos (one per map). A `demo_collections`
-- row groups them (keyed by the match's source + external_id), and each demo points back via
-- `demos.collection_id`. To let one match id resolve to ALL its map demos, `demo_external_refs` is
-- relaxed from globally-unique (source, external_id) to unique-per-(demo, source, external_id):
-- the ref is now one-to-many, so `by-ref` returns every map (disambiguate with `?map=`).

CREATE TABLE demo_collections (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  owner_user_id BIGINT UNSIGNED NOT NULL,
  source        VARCHAR(32),                              -- 'hltv' | 'faceit' | <slug> | NULL (ad-hoc)
  external_id   VARCHAR(128),                             -- the match id at that source | NULL
  name          VARCHAR(255),
  meta          JSON,
  created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  -- One collection per (owner, source, match). NULL source/external_id are distinct in MySQL
  -- unique indexes, so ad-hoc collections (no ref) never collide.
  UNIQUE KEY uq_owner_source_ext (owner_user_id, source, external_id),
  KEY idx_coll_source_ref (source, external_id),
  CONSTRAINT fk_coll_user FOREIGN KEY (owner_user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

ALTER TABLE demos
  ADD COLUMN collection_id BIGINT UNSIGNED NULL AFTER owner_user_id,
  ADD KEY idx_demo_collection (collection_id),
  ADD CONSTRAINT fk_demo_collection FOREIGN KEY (collection_id)
      REFERENCES demo_collections(id) ON DELETE SET NULL;

-- Allow a (source, external_id) to map to MANY demos (one per map of a match). Uniqueness moves to
-- (demo_id, source, external_id) so re-attaching the same ref to the same demo stays idempotent.
ALTER TABLE demo_external_refs
  DROP KEY uq_source_ref,
  ADD KEY idx_source_ref (source, external_id),
  ADD UNIQUE KEY uq_demo_source_ref (demo_id, source, external_id);
