# Stage 11 — Real-World Demo Handling

**Goal:** parse the messy demos you'll actually receive — correctly, or rejected cleanly
with a useful error. The ported logic assumes clean GOTV demos; production demos aren't.

## Context

The old `RoundLoader.worker.js` fixes a canonical player set from "the first populated tick"
and the old scoring logic predates CS2's MR12. Both break on real demos. Define explicit
behavior for each case below. Decide **game scope** first: **CS2 (Source 2) only**, or also
legacy CSGO demos? (Different format; `scales.js` still lists `de_inferno_s2`, `de_cache`.)
Recommend CS2-only to start, reject CSGO with a clear message.

## 11.1 Cases to handle

1. **GOTV vs POV demos.** Detect from the header. POV (client-recorded) has one player's
   full data, odd tickrate, missing entities → either support in a degraded mode or reject
   with "POV demos unsupported." Do not silently produce a broken viewer.
2. **Tickrate variance.** 64-tick CS2 GOTV vs 128-tick legacy/FACEIT. The viewer interpolates
   between ticks — read tickrate from the header, never hardcode. Verify playback speed math.
3. **MR12 + overtime scoring.** CS2 is first-to-13, **side switch at round 12**, OT in MR3
   blocks with side switches. Port and **fix** `_process_rounds` score logic for this; the
   old code's halftime assumptions may be CSGO-era. Validate against known final scores.
4. **Round win-reason enums** changed in CS2 — map them explicitly; unknown reasons degrade
   to a generic label, not a crash.
5. **Disconnects / subs / slot reuse.** Players leave, reconnect, get subbed; steamids and
   player slots shift mid-match. **Harden the canonical-player logic** — key strictly by
   steamid, tolerate a roster that changes across rounds, handle 5v4 states. This is the
   most common real-world breakage.
6. **Non-players in the player set** — coaches, casters, spectators, bots. Filter to actual
   participants (team membership + connected + not a bot) before building payloads.
7. **Warmup / knife / freeze rounds.** The old `round_index > 0` filter is a start; confirm
   knife-round and warmup exclusion and correct first-real-round indexing.
8. **Corrupt / truncated demos.** Server crashes cut demos mid-match. Parse defensively;
   produce a partial-but-valid result where possible, else fail the job with a precise error
   and the tick it died on.

## 11.2 Approach

- A **pre-parse probe** of the header classifies the demo (GOTV/POV, game version, map,
  tickrate, expected rounds) and decides support/reject *before* the expensive full parse.
- Wrap parsing so any per-round failure degrades that round (or fails cleanly) without
  nuking the whole demo.
- Emit a structured `parse_report` into `demos.meta`: detected type, tickrate, rounds
  found vs expected, players, anomalies — invaluable for debugging and the corpus (Stage 15).

## Reuse from existing code

- `demo_processor.py` `_process_rounds` / `_process_single_round` → scoring (must be
  re-verified for MR12/OT), bomb/round tick mapping.
- `RoundLoader.worker.js` canonical-player block → reimplement steamid-keyed + roster-change
  tolerant.
- `demoparser2/examples/round_time`, `scoreboard`, `kills_per_round` → reference for correct
  CS2 event handling.

## Acceptance criteria

- **Tests (required for Done):** the tests this phase needs are written and green in CI — see
  `TESTING.md` for stack/layout and its per-phase table for exactly what to cover.

- A corpus (Stage 15) with GOTV, POV, 128-tick, OT, disconnect/sub, spectators/bots, knife,
  and a truncated demo each either parses correctly or is rejected with a precise reason.
- Final scoreline (incl. a map that went to OT) matches the known result.
- Player slots stay stable across a mid-match disconnect/reconnect.
- POV and CSGO demos are detected and rejected pre-parse, not after a wasted full parse.
