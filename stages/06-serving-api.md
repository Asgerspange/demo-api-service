# Stage 06 — Serving API

**Goal:** the read endpoints the viewer consumes — demo metadata, the round index,
per-round payloads (lazy), and map/scale data — all aggressively cacheable and identical in
shape whether hit directly or through a proxy.

## Context

This is the contract both the owner API and every customer proxy expose (Stage 04 §4.2).
The old `DemoController::getChunk` already serves gzipped per-round JSON with
`Content-Encoding: gzip` — keep that streaming-from-storage idea, but read from object
storage and lean on immutability + CDN.

## 6.1 Request contract (`/v1`)

```
GET /v1/demos/{demoId}
  -> 200 {
       id, map, name, payload_version, round_count, duration_ticks,
       refs: [ { source:'hltv', external_id:'2378001' } ],   # external identifiers
       players: [...steam summaries...],
       rounds: [ { round_index, meta:{start,freeze_end,end,official_end,winner,reason,
                                       ct_score,t_score} } ],
       map_ref: { scale, radar_url, radar_lower_url?, levels?[] }
     }
  Cache-Control: public, max-age=60        # metadata can change until 'ready'; short TTL

GET /v1/demos/by-ref/{source}/{external_id}
  -> resolves (source, external_id) -> demo, then returns the SAME body as
     GET /v1/demos/{demoId}. 404 if no such ref (or the caller's key doesn't own it).
     e.g. GET /v1/demos/by-ref/hltv/2378001
  Cache-Control: public, max-age=60

GET /v1/demos/{demoId}/rounds/{i}
  -> 200 <per-round payload bytes>          # gzipped JSON (v1) or binary columns (v2)
  Content-Type: application/json | application/octet-stream
  Content-Encoding: gzip                    # when payload is gzipped JSON
  ETag: "<sha of object>"
  Cache-Control: public, max-age=31536000, immutable   # parsed data never changes

GET /v1/maps/{map}
  -> 200 { name, display_name, pos_x, pos_y, scale, rotate, zoom,
           selections:[{name,altitude_max,altitude_min}], radar_url }
  Cache-Control: public, max-age=86400

GET /v1/demos?cursor=&limit=&map=&status=
  -> 200 { items:[ {id, map, name, status, round_count, created_at, refs} ], next_cursor }
     # the caller's owned demos; cursor-paginated, filterable. For dashboards/integrations.
```

The viewer negotiates `payload_version` from `GET /v1/demos/{id}` and decodes accordingly;
old versions stay served per the **Stage 17** deprecation policy (embeds can't be force-updated).

- Per-round payloads are **immutable** once `ready` → serve with `immutable` + ETag and let
  CDN/browser cache forever (gap #11). Support conditional `If-None-Match` → 304.
- Serve payloads via **CDN URLs with bunny Token Authentication** — the API mints a signed,
  short-TTL URL *after* auth + origin-lock + rate-limit, and the browser fetches from the
  edge. This closes the scrape/hotlink hole (the raw CDN path otherwise bypasses all auth).
  Full design in **Stage 13**; do not ship public, guessable payload URLs.
- A demo that isn't `ready` → `409`/`425` with the job status so the viewer can poll.
- Authz: the `AuthContext` (Stage 03) gates access; demos are owned by a user, so a key can
  only read demos its user owns (or that are explicitly public, if you add that later).
- `by-ref` resolution: `(source, external_id)` is globally unique → look up `demo_external_refs`,
  then apply the same ownership check. To a caller who doesn't own the demo it returns 404
  (not 403), so external ids aren't probeable across tenants. The lookup is a cheap indexed
  hit; cache the `(source,external_id)→demo_id` mapping in Redis like other metadata.

## 6.2 Map / scale data

Serve directly from the seeded `map_metadata` table (Stage 02; sourced from
`map_metadata.sql`). `/v1/maps/{map}` returns the calibration (`pos_x/pos_y/scale/rotate/
zoom`), the `selections` for multi-level maps (nuke/vertigo/baggage), and `radar_url` =
the row's `image_path` — an existing bunny CDN asset, **mostly SVG** on `csstrats.b-cdn.net`
(a few legacy `.png`/local `/images/maps/...`). The viewer uses this to convert world X/Y →
radar pixel coordinates and to load the radar image. Do **not** re-derive this from
`scales.js`; the table is authoritative. `/v1/maps` (no arg) can return the full list.

## 6.3 Caching layer

- Object payloads: immutable + ETag (above). This is ~all of your read performance.
- Metadata: short TTL in Redis (port the intent of `CacheService.php`) keyed by demo id +
  `payload_version`; invalidate on status change.
- Put a CDN in front of `/v1/demos/{id}/rounds/*` and `/v1/maps/*` (Stage 09). The proxy
  contract requires customers to pass these headers through so their CDN benefits too.

## 6.4 Response shape stability

Version everything: `/v1` path + `payload_version` in metadata. Embedded viewers on sites
you don't control must keep working when you ship v2 payloads — the viewer reads
`payload_version` from `/v1/demos/{id}` and decodes accordingly (Stage 07).

## Reuse from existing code

- `DemoController::getChunk` / `getAdminChunk` → the gzipped-per-round streaming response
  pattern (reads now come from object storage, not `demo_rounds.frame_data`).
- `DemoController::show` / `rounds` / `getDemoRounds` → the metadata + round-index shape.
- `map_metadata.sql` → the authoritative calibration + bunny CDN radar URLs behind
  `/v1/maps`. `MapController.php` + `scales.js` are the older equivalents (cross-check only).
- `CacheService.php` → caching intent (reimplement on Redis + HTTP cache headers).

## Acceptance criteria

- **Tests (required for Done):** the tests this phase needs are written and green in CI — see
  `TESTING.md` for stack/layout and its per-phase table for exactly what to cover.

- `GET /v1/demos/{id}` returns metadata + round index + `map_ref` + `refs`.
- `GET /v1/demos/by-ref/hltv/2378001` returns the same demo as its numeric id; an unknown or
  unowned ref returns 404.
- `GET /v1/demos/{id}/rounds/{i}` returns the exact bytes the viewer worker expects, with
  `immutable` + `ETag`; a second request with `If-None-Match` → 304.
- `GET /v1/maps/de_mirage` returns the calibration + `radar_url`
  (`https://csstrats.b-cdn.net/maps/de_mirage.svg`) straight from `map_metadata`.
- Identical responses whether called directly (client key) or through the reference proxy
  (server key) — same bodies, same caching headers.
- Requesting a not-yet-ready demo returns a pollable status, not a 500.
