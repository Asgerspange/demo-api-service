# Stage 12 — Map Versioning & Calibration

**Goal:** keep world→radar alignment correct as Valve reworks maps, and degrade gracefully
for maps you have no radar for.

## Context

`map_metadata` (Stage 02) is static calibration. When Valve reworks a map (Dust2, Inferno,
Train have all shifted; Anubis/Overpass rotate in/out), the offset/scale drift and every
player position renders wrong — **silently**, until someone notices. You need map *identity*
per demo, drift detection, a recalibration workflow, and an unknown-map fallback.

## 12.1 Per-demo map identity

- Capture from the demo header what's available: map `name` and any version signal the
  engine exposes (workshop id / map CRC / version). Store on the demo (`demos.map_version`,
  nullable) and in the `parse_report`.
- `map_metadata` gains a **`version`** (and optionally a `valid_from`/`valid_to`) so a single
  map name can have multiple calibrations over time. Resolve calibration by `(name,
  version)`, falling back to the latest known if version is absent.

```sql
ALTER TABLE demos ADD COLUMN map_version VARCHAR(64);   -- workshop id / CRC if available
ALTER TABLE map_metadata ADD COLUMN version VARCHAR(64) DEFAULT 'live';
-- relax the unique key to (name, version)
```

## 12.2 Drift detection

- At parse, sample a few **ground-truth positions** (bomb sites, spawns from the demo) and
  check they land in plausible radar regions under the resolved calibration. A gross mismatch
  → flag `calibration_suspect` on the demo + alert, rather than shipping a wrong viewer.
- Track per-map parse counts vs flags so a Valve update that breaks a map surfaces fast.

## 12.3 Recalibration workflow

- A small owner tool (extends the admin, Stage 03): load a demo on a map, overlay the radar,
  nudge `pos_x/pos_y/scale/rotate/zoom` until players sit correctly, save a new
  `map_metadata` row/version. This is the manual loop that keeps you current after reworks.
- New radars upload to the existing maps zone (`csstrats.b-cdn.net`); the row's `image_path`
  points at them. Mostly SVG.

## 12.4 Unknown / community maps

- No `map_metadata` row → don't render into a void. Either (a) reject with "map not
  supported," or (b) render a neutral grid with positions but no radar, clearly labeled.
  Decide per product needs; default to a clear "unsupported map" state.
- Workshop/community maps are out of scope for calibrated radars but should fail gracefully.

## Reuse from existing code

- `map_metadata.sql` / `scales.js` → existing calibrations (treat as `version='live'` seeds).
- `MapController.php` → old map-update admin patterns for the recalibration tool.

## Acceptance criteria

- **Tests (required for Done):** the tests this phase needs are written and green in CI — see
  `TESTING.md` for stack/layout and its per-phase table for exactly what to cover.

- A demo on a reworked map resolves the correct calibration version, or is flagged
  `calibration_suspect` when none matches — never silently misaligned.
- An unknown map yields a clear unsupported/neutral state, not a blank or crashed viewer.
- Adding/recalibrating a map = upload radar + one `map_metadata` row; no code change.
