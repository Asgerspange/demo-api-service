# Stage 15 — Test Corpus & Regression Harness

**Goal:** make "we keep it working through every CS2 update" true and provable. This is the
safety net for the parser-maintenance treadmill that is your core value.

## Context

Valve breaks the demo format on updates; awpy/demoparser2 get patched; your `_player_props`
and payload code shift. Without a pinned corpus and golden outputs, every update is roulette
and regressions reach customers silently.

## 15.1 The corpus

A small, version-controlled (pointer to object storage; demos are large) set covering the
Stage 11 cases and the map matrix:
- A 64-tick MM GOTV demo, a 128-tick (legacy/FACEIT) demo, a pro demo, **a demo that went to
  overtime**, a **POV** demo, a **truncated/corrupt** demo, a demo with a **disconnect/sub**.
- One demo per **active-duty map**, plus **a reworked map** and **a community/unknown map**.
- Each with known ground truth: final score, round count, player roster, a few sampled
  positions.

## 15.2 Golden-file parse tests

- For each corpus demo, snapshot key parse outputs (round count, scores, per-round meta,
  sampled tick positions, player set) as golden files. A parser/awpy bump that changes them
  fails CI with a diff — you decide if it's a fix or a regression.
- Keep goldens per `payload_version` so format bumps are intentional, reviewed changes.

## 15.3 Viewer visual regression

- Render representative rounds to canvas headlessly and snapshot. Compare per map so a
  calibration or render regression (Stage 12) is caught visually.
- Cover multi-level maps (nuke/vertigo) and at least one SVG radar path.

## 15.4 CI gate + prod feedback

- Run the corpus on every change to: the parser dep (awpy/demoparser2 pin), the payload
  builder, the viewer renderer. Block merge on unreviewed diffs.
- Feed **production parse-failure samples** back into the corpus: when a real demo fails,
  add a (sanitized) reproducer so it never regresses again.
- Track prod parse-success rate as a metric (Stage 08); a dip after a Valve update is your
  signal to patch.

## Reuse from existing code

- `demoparser2/examples/*` → reference expected outputs for events/scoreboard/round time.
- Stage 11 `parse_report` → the structured output to snapshot.

## Acceptance criteria

- **Tests (required for Done):** the tests this phase needs are written and green in CI — see
  `TESTING.md` for stack/layout and its per-phase table for exactly what to cover.

- CI runs the corpus on every parser/payload/renderer change and fails on unreviewed output
  or visual diffs.
- The corpus covers every Stage 11 case and the full active-duty map matrix + a reworked and
  an unknown map.
- A newly discovered prod parse failure can be added as a reproducer in minutes.
