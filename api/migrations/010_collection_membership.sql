-- Stage 19 — many-to-many collection membership.
--
-- demos.collection_id was a single pointer, so a demo could belong to only ONE collection. With
-- cross-tenant dedup, a demo shared between tenants must appear in EACH tenant's own collection
-- (collections are per-tenant, keyed by owner). `collection_demos` makes membership many-to-many;
-- serving lists a collection through this table. demos.collection_id is left in place (the creating
-- tenant's collection) but is no longer the source of truth for listing.

CREATE TABLE collection_demos (
  collection_id BIGINT UNSIGNED NOT NULL,
  demo_id       BIGINT UNSIGNED NOT NULL,
  added_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (collection_id, demo_id),
  KEY idx_cd_demo (demo_id),
  CONSTRAINT fk_cd_coll FOREIGN KEY (collection_id) REFERENCES demo_collections(id) ON DELETE CASCADE,
  CONSTRAINT fk_cd_demo FOREIGN KEY (demo_id) REFERENCES demos(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Backfill from the existing single-pointer column.
INSERT INTO collection_demos (collection_id, demo_id)
  SELECT collection_id, id FROM demos WHERE collection_id IS NOT NULL;
