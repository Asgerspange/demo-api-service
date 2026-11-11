# CS Demoviewer — embeddable 2D viewer

A single-file, zero-dependency 2D CS2 demo replay you drop into any web page. One `<script>` tag,
one `init(...)` call. ~40 KB, no framework, renders to a `<canvas>`, decodes round data in an inlined
Web Worker, and works on desktop and mobile.

- **API reference** (ingesting demos, serving endpoints): [../deploy/API.md](../deploy/API.md)
- **Versioning / support policy:** [../deploy/DEPRECATION.md](../deploy/DEPRECATION.md)

---

## Quick start

Load the bundle from the demos CDN root and initialize:

```html
<div id="viewer" style="width:100%;height:600px"></div>
<script src="https://demos.b-cdn.net/viewer.js"></script>
<script>
  const v = CSDemoViewer.init({
    el: '#viewer',
    apiBase: 'https://api.csstrats.dk',
    demoId: 1234,
    clientKey: 'pk_live_…',     // origin-locked client key (direct mode)
    autoplay: true,
  });
</script>
```

`init(opts)` returns the **instance API** (see below). The bundle is published at the **root of the
demos CDN** (`https://<demos-pull-zone>/viewer.js`) by `deploy/publish_viewer.sh`; it's cached
`max-age=300`, so a re-publish rolls forward within ~5 minutes (purge the Pull Zone for an instant
update). Forward/back compatibility is handled by **payload-version negotiation** (below), not URL
pinning.

### As a Web Component

```html
<script src="https://demos.b-cdn.net/viewer.js"></script>
<cs-demoviewer
  demo-id="1234"
  api-base="https://api.csstrats.dk"
  client-key="pk_live_…"
  autoplay
  skip-freezetime
  style="width:100%;height:600px"></cs-demoviewer>
```

The component renders into a shadow root (host CSS can't leak in or out). Attributes mirror the init
options: `demo-id`, `api-base`, `client-key`, `round`, `autoplay`, `skip-freezetime`, `auto-advance`,
`scoreboard`, `speed`, `theme` (JSON string).

---

## Two ways to talk to the API

### Direct mode (client key in the page)

```js
CSDemoViewer.init({ el: '#v', demoId: 1234, apiBase: 'https://api.csstrats.dk', clientKey: 'pk_live_…' });
```

The viewer sends `Authorization: Bearer pk_live_…`. The key is **origin-locked**, so it's safe in page
source — a request from a non-allow-listed origin is rejected. Simplest to set up.

### Proxy mode (no key in the browser)

```js
CSDemoViewer.init({ el: '#v', demoId: 1234, apiBase: 'https://your-site.com/cs' });
```

No `clientKey`. Your backend forwards `/cs/v1/**` to the API, injecting `X-Server-Key` +
`X-End-User` server-side. Nothing secret reaches the browser. Reference proxies (PHP + Node) are in
[`examples/`](examples/README.md); the transparency contract is described in
[../deploy/API.md](../deploy/API.md) §Proxy mode.

---

## Init options

| Option | Type | Default | Description |
|---|---|---|---|
| `el` | string \| Element | — | **Required.** Container (selector or node). The viewer fills it. |
| `apiBase` | string | `''` | API origin (direct) or your proxy prefix (proxy mode). |
| `demoId` | number | — | **Required.** The demo to play (resolve it via the API — e.g. `by-ref?map=`). |
| `clientKey` | string | `null` | Client key for direct mode. Omit for proxy mode. |
| `round` | number | first | Initial round index. |
| `tick` | number | — | Initial tick to seek to (used by deep-links). |
| `follow` | string | — | steamid to highlight/follow. |
| `share` | string | — | A share-state string to restore (`d=…&r=…&t=…&f=…`); see Deep-links. |
| `deepLink` | bool | `true` | Read `#csdv=…` from the page URL on load. Set `false` to ignore it. |
| `autoplay` | bool | `false` | Start playing once loaded. |
| `skipFreezetime` | bool | `false` | Start each round at the end of freezetime (like match replays). |
| `autoAdvance` | bool | `false` | Auto-load + play the next round when one ends. |
| `speed` | number | `1` | Playback speed (`0.5`, `1`, `2`, `4`). |
| `scoreboard` | bool | `true` | Show the in-viewer scoreboard strip. |
| `theme` | object | — | Full visual override — see Theming. |
| `labels` | object | — | i18n string overrides — see Localization. |
| `timers` | object | — | Timer tuning (`tickRate`, `roundSeconds`, `bombSeconds`, …). |
| `hooks` | object | — | Event callbacks — see Hooks. |

---

## Instance API

`init()` returns an object:

```js
const v = CSDemoViewer.init({ … });

v.play(); v.pause();
v.seek(tickIndex);          // jump within the current round
v.setRound(i);              // load + show round i
v.setSpeed(2);              // 0.5 | 1 | 2 | 4
v.setScoreboard(false);     // toggle the scoreboard strip
v.fullscreen();             // toggle fullscreen
v.setFollow('7656…');       // highlight/follow a player (null clears)
v.shareUrl();               // → a deep-link URL to the exact current moment
v.snapshot();               // per-player state at the current tick (for a host-side HUD)
v.destroy();                // tear down: worker, listeners, DOM — leaves nothing behind

v.meta;                     // the loaded demo metadata
v.roundIndex;               // current round
v.tickIndex;                // current tick index
```

`destroy()` is important in SPAs — call it when unmounting so the worker and listeners are released.

---

## Hooks

```js
CSDemoViewer.init({
  …,
  hooks: {
    onReady:      (api)            => {},                 // demo loaded, first round shown
    onError:      (err)            => {},                 // load/decode/auth/unsupported-map error
    onRoundChange:(round, meta)    => {},                 // round changed
    onTick:       (tickIndex, tick)=> {},                 // every rendered frame
    onTimestamp:  (round, tick)    => {},                 // shareable moment changed (for persisting state)
    onShare:      (url, state)     => {},                 // user copied a share link (🔗 control)
    onDeprecation:(info)           => {},                 // the demo's payload_version is near sunset
  },
});
```

---

## Deep-links — "share this clutch"

The viewer encodes the exact moment — demo + round + tick (+ followed player) — into a `#csdv=`
URL fragment, and restores it on load (unless `deepLink: false`).

```js
const url = v.shareUrl();
// → https://your-page/...#csdv=d%3D1234%26r%3D5%26t%3D1840
```

Paste that URL and the viewer opens at round 5, tick 1840. The built-in **🔗 control** copies it and
fires `onShare`. You can also build one server-side and pass it via the `share` option. This is both a
UX feature and the cheapest distribution lever — shared clutches spread embeds.

---

## Multi-demo matches (collections)

An HLTV match is several demos (one per map). Resolve the match, build a map picker, and re-point the
viewer per map:

```js
const r = await fetch(`${apiBase}/v1/collections/by-ref/hltv/2378001`, {
  headers: { Authorization: `Bearer ${clientKey}` } });
const { demos } = await r.json();          // [{ id, map, … }, …]

// render a map picker; on click:
v.destroy();
v = CSDemoViewer.init({ el: '#v', apiBase, clientKey, demoId: picked.id, autoplay: true });
```

(Or use `GET /v1/demos/by-ref/hltv/2378001?map=de_nuke` to get one map's `demoId` directly.)

---

## Theming

Every visual is overridable via `theme`. A few common ones:

```js
theme: {
  accent: '#f5a623',        // scoreline / active controls
  ctColor: '#7a9bcb',       // CT team color (markers, tracers, scoreboard)
  tColor: '#d1c185',        // T team color
  background: '#0e0f12',    // canvas + container background
  controlBg: 'rgba(0,0,0,0.55)', controlColor: '#ffffff',
  followColor: '#ffd54f',   // highlight ring on a followed player
  // sizes
  playerIconSize: 26, weaponIconSize: 11, nameFontSize: 11, radarOpacity: 1,
  // layer toggles
  showWeaponFire: true, showGrenades: true, showSmokes: true, showWeapons: true,
  showNames: true, showHud: true, showTimer: true, showKillfeed: true,
  // which controls appear (order preserved)
  controls: ['play', 'timeline', 'round', 'speed', 'share', 'fullscreen'],
  // bring your own marker/weapon SVGs
  assetBase: 'https://your-cdn', ctIconUrl: '…/ct.svg', tIconUrl: '…/t.svg',
}
```

Drop `'share'`/`'fullscreen'`/etc. from `controls` to hide them; set any `show*` to `false` to drop a
layer. Markers, weapon icons, and team colors can all be swapped to match your brand.

---

## Localization (i18n)

No hardcoded English — pass `labels` to translate any string. `{n}` / `{round}` / `{map}` are
interpolated.

```js
labels: {
  play: 'Lire', pause: 'Pause', round: 'Manche {n}',
  loadingRound: 'Chargement manche {round}…',
  unsupportedMap: 'Carte « {map} » non prise en charge.',
}
```

---

## Keyboard & touch

- **Keyboard** (when the viewer has focus): `Space`/`k` play-pause · `←`/`→` seek ±1s · `↑`/`↓` (or
  `.`/`,`) step round · `f` fullscreen. Controls have ARIA labels; the root is `role="application"`.
- **Touch / mobile:** one-finger drag = pan, two-finger pinch = zoom, the timeline scrubs; tap targets
  grow on narrow screens. The canvas is DPR-aware.

---

## Versioning & compatibility

- The bundle is served from the **demos CDN root** (`https://<demos-pull-zone>/viewer.js`,
  `max-age=300`) and rolls forward on re-publish. Embeds don't pin a URL version.
- The viewer reads `payload_version` from the demo metadata and **decodes whatever version it's told**.
  If the API later serves a newer format your pinned bundle can't read, the viewer shows a clear
  "update the embed" message (never a broken render); if you're pinned to a soon-to-sunset version it
  logs a console warning and fires `onDeprecation`. Support windows: [../deploy/DEPRECATION.md](../deploy/DEPRECATION.md).

---

## Building from source

```bash
cd viewer
npm ci
npm run build        # → dist/viewer.js (IIFE, script-tag) + dist/viewer.esm.js (ESM)
npm test             # vitest: decode, render snapshots, UX modules, jsdom instance wiring
```

Publish to the CDN with [`../deploy/publish_viewer.sh`](../deploy/publish_viewer.sh) (see
[../deploy/RELEASE.md](../deploy/RELEASE.md) §4).
