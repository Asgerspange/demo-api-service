-- Stage 12 — map calibration versioning. A single map name can have multiple calibrations over
-- time (Valve reworks shift offset/scale), resolved by (name, version). Existing rows become the
-- 'live' version. `demos.map_version` already exists (migration 001).

ALTER TABLE map_metadata
  ADD COLUMN version VARCHAR(64) NOT NULL DEFAULT 'live';

-- Relax the unique key from (name) to (name, version) so reworked-map calibrations can coexist.
ALTER TABLE map_metadata DROP INDEX name;
ALTER TABLE map_metadata ADD UNIQUE KEY uq_name_version (name, version);
