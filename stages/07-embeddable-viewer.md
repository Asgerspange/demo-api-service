# Stage 07 — Embeddable 2D Viewer

**Goal:** a single-file, pure-JS, drop-anywhere 2D playback viewer. No Vue. Small memory
footprint. Customizable per host site. Talks to either the owner API (client key) or a
customer proxy (no secret) via the Stage 06 contract.

## Context

Brief: *"a file implementable on ANY website that creates the 2D viewer, customizable based
on the site; purely a 2D viewer (no stats/heatmaps); pure JS is fine; optimize hard for
speed and small browser memory."*

You already have the hard parts solved in the old Vue app — **port, don't reinvent**:
- `RoundLoader.worker.js` — round JSON → columnar TypedArrays with zero-copy transfer.
- `Demo/2D/composables/useRenderer.js` (43 KB) — the canvas draw loop.
- `useCanvas.js`, `usePlayback.js`, `useRoundData.js`, `useWeapons.js`, `useDemo.js`.
- `scales.js` — world→radar coordinate mapping.

The job here is to **strip these out of Vue** into framework-free modules and wrap them in a
clean embed API.

## 7.1 Distribution & embedding

Build to `viewer/dist/viewer.js` as both UMD (global `CSDemoViewer`) and ESM. Two ways to embed:

```html
<!-- Script tag -->
<div id="v"></div>
<script src="https://cdn.owner.gg/viewer.js"></script>
<script>
  CSDemoViewer.init({ el: '#v', demoId: 123, apiBase: 'https://api.owner.gg',
                      clientKey: 'pk_live_…', theme: {...} });
</script>

<!-- Or Web Component -->
<cs-demoviewer demo-id="123" api-base="https://customer.com/cs"></cs-demoviewer>
```

- Ship the worker **inlined as a Blob URL** (or bundled same-origin) so cross-origin embeds
  don't trip Worker CORS (gap #10). Do not load the worker from a bare cross-origin URL.
- Zero hard dependencies. No global CSS leakage — render inside a shadow DOM (Web Component)
  or a scoped container so it can't clash with the host site's styles.
- Keep the bundle small; lazy-load nothing at runtime that blocks first paint except the
  current round.

## 7.2 Config / customization API

```js
CSDemoViewer.init({
  el: '#v' | HTMLElement,
  demoId: 123,
  apiBase: 'https://api.owner.gg' | 'https://customer.com/cs',
  clientKey: 'pk_live_…',          // omit in proxy mode
  round: 0,                         // initial round
  autoplay: false,
  speed: 1,
  theme: {                          // per-site customization
    accent, ctColor, tColor, background, font,
    radarOpacity, playerDotSize, showWeaponFire, showGrenades, showSmokes,
    showNames, showHud, controls: ['play','timeline','round','speed'],
  },
  hooks: { onReady, onRoundChange, onTick, onError },  // host-site integration
});
// instance API: .play() .pause() .seek(tick) .setRound(i) .setSpeed(x) .destroy()
```

The viewer branches on `clientKey`: present → send `Authorization: Bearer pk_…`; absent →
send nothing (proxy injects the server key). Everything else identical (Stage 04 §4.3).

## 7.3 Data flow & memory budget

1. On init: `GET {apiBase}/v1/demos/{demoId}` → metadata, round index, `payload_version`,
   `map_ref`. Fetch the radar from `map_ref.radar_url` once — it's an existing bunny CDN
   asset, **usually SVG** (a few legacy PNG). Load it into an `Image`/`ImageBitmap` and draw
   to canvas; SVG scales crisply at any zoom/DPR, so prefer drawing it to an offscreen layer
   at the displayed resolution. Handle both SVG and PNG `radar_url` transparently.
2. On round select: worker fetches `GET {apiBase}/v1/demos/{demoId}/rounds/{i}`, decodes to
   columnar TypedArrays (port `RoundLoader.worker.js`), transfers buffers back zero-copy.
3. Renderer draws current tick onto canvas from the TypedArrays; world→pixel via the
   `scales.js` math + `map_ref.scale`.
4. **Memory discipline (the brief's "small browser memory"):**
   - Hold **only the current round** (+ optionally prefetch the next) in memory; free prior
     rounds' buffers on round change. This is why per-round lazy loading matters.
   - Columnar TypedArrays (not arrays of objects) — already the old worker's design.
   - Reuse a single canvas + offscreen layer; don't allocate per frame.
   - Cap any client-side cache (e.g. keep ≤2 decoded rounds).
   - If `payload_version` 2 (server-side columnar binary) is available, the worker maps it
     almost directly → less GC churn.
5. Honor `immutable` cache headers — the browser/CDN caches rounds; revisiting a round is free.

## 7.4 Rendering scope (keep it lean)

Players (dot + facing + team color + dead/alive + flash), bomb (carried/dropped/planted/
defusing), weapon fire flashes, grenades + smokes/infernos with their lifetimes, basic
timeline/round/speed controls, and a minimal player HUD (name/hp/armor/weapon). **No** stat
panels, **no** heatmaps, **no** 3D. Port the draw logic from `useRenderer.js`, dropping
anything stats-related.

## 7.5 Robustness for "any website"

- Tolerate being placed in any container size → responsive canvas (DPR-aware).
- Fail soft: bad demo id / 409 not-ready → friendly message + retry/poll; 429 → backoff
  message; auth error → clear console + `onError` hook.
- No reliance on host globals; clean `destroy()` that terminates the worker and frees buffers.

## Reuse from existing code

- `RoundLoader.worker.js` → port verbatim as the decode worker (it already supports a
  configurable base URL → rename to `apiBase`).
- `Demo/2D/composables/useRenderer.js`, `useCanvas.js`, `usePlayback.js`, `useRoundData.js`,
  `useWeapons.js` → de-Vue into plain modules.
- `scales.js` → the world→radar transform math (offset/scale/rotate/zoom). The values
  themselves come from `/v1/maps` (the `map_metadata` table), not from `scales.js`.
- `Demo/2D/options.js` (e.g. `FLASH_FADE_TICKS`) → constants.

## Acceptance criteria

- **Tests (required for Done):** the tests this phase needs are written and green in CI — see
  `TESTING.md` for stack/layout and its per-phase table for exactly what to cover.

- A single `<script>` + `CSDemoViewer.init(...)` renders a playable round on a blank HTML
  page with no build step and no other dependencies.
- Works in both direct (clientKey) and proxy (no key) modes against the same demo.
- Switching rounds frees the previous round's buffers (verify in DevTools memory) and keeps
  a bounded footprint across a full match.
- Theme options visibly change colors/toggles; `destroy()` leaves no worker or listeners.
- Renders correctly on at least dust2, mirage, and a multi-level map (nuke or vertigo).
