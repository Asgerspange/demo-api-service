# Stage 17 — Viewer UX Completeness & Compatibility

**Goal:** make the embed feel complete, work on mobile, and keep working forever on sites you
can't force-update. Still strictly a 2D viewer — no stats/heatmaps.

## Context

Stage 07 builds the core viewer. This stage closes the UX and longevity gaps that make it
production-grade for third-party embedding.

## 17.1 Shareable deep-links

- Encode `demoId + round + tick` (and optional followed player) into a shareable URL /
  embed param; the viewer restores exactly that moment on load.
- Both a UX feature and your cheapest distribution lever — "share this clutch" spreads embeds
  on news/social. Fire an `onShare`/`onTimestamp` hook for host integration.

## 17.2 Mobile / touch / responsive

- "Any website" includes phones (CS audiences skew mobile in BR/RU/SEA). Touch gestures
  (pan/zoom/scrub), tap targets, responsive layout, DPR-aware canvas, and a perf budget for
  low-end devices (cap redraw work, respect the Stage 07 memory discipline).

## 17.3 Expected in-viewer elements

- **Round / bomb / defuse timers** mapped from tick → in-game clock (round time, 40s bomb,
  5/10s defuse) — expected in any 2D viewer.
- **Killfeed** — the data is already in the per-round payload (`kills`); render it.
- Round selector, timeline scrub, play/pause, speed — from Stage 07.

## 17.4 i18n & accessibility

- No hardcoded English strings — a small label dictionary so host sites can localize.
- Keyboard controls (space, arrows, round step) and ARIA labels on controls.

## 17.5 Version pinning & deprecation (longevity)

- Embedded viewers pin a bundle version (Stage 09) and read `payload_version` from
  `/v1/demos/{id}` to decode (Stage 06). You **cannot** force-update embeds in the wild, so:
  - keep **old `payload_version`s served** until a published sunset date,
  - the viewer negotiates and decodes whatever version it's told,
  - publish a **deprecation policy** (how long each `/v1` + payload version is supported) and
    surface a console warning when a host pins something near end-of-life.

## Reuse from existing code

- `Demo/2D/Slider.vue`, `Scoreboard.vue`, `options.js`, `useWeapons.js` → UX/control patterns
  and constants (de-Vue'd into the vanilla viewer).
- `RoundLoader.worker.js` version-aware decode → `payload_version` negotiation.

## Acceptance criteria

- **Tests (required for Done):** the tests this phase needs are written and green in CI — see
  `TESTING.md` for stack/layout and its per-phase table for exactly what to cover.

- A shared link opens at the exact round + tick (+ followed player) it encodes.
- The viewer is usable via touch on a phone, responsive across container sizes and DPRs.
- Round/bomb/defuse timers and a killfeed render correctly.
- Labels are localizable; core controls are keyboard-operable.
- A viewer bundle pinned to an older `payload_version` still loads against the current API.
