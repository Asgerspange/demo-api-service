# CS Demoviewer — API reference

The HTTP API for ingesting CS2 demos and serving the 2D-replay data the embeddable viewer reads.
Most integrators only need the **embed** (see [VIEWER.md](../viewer/README.md)); this document is for
**ingesting demos** and for building directly against the serving endpoints.

- **Base URL:** `https://api.csstrats.dk`
- **API version:** `v1` (path-prefixed; see [DEPRECATION.md](DEPRECATION.md) for the support policy)
- **Content type:** JSON, except per-round payloads (gzipped JSON bytes)
- All responses are JSON unless noted; errors are `{ "detail": "<message>" }` with a 4xx/5xx status.

---

## Authentication

Every request carries an **API key**. There are two kinds:

| Kind | Prefix | Where it's used | How it's sent |
|---|---|---|---|
| **Client key** | `pk_live_…` | Public — embedded in a web page (the viewer). Read-only, origin-locked. | `Authorization: Bearer pk_live_…` (or `X-Client-Key:`) |
| **Server key** | `sk_live_…` | Secret — your backend. Can ingest + delete. | `X-Server-Key: sk_live_…` + `X-End-User: <id>` |

Keys are issued to you by the operator. Treat the **server key as a secret** — never ship it to a
browser.

### Client keys (direct, browser)

- Sent as `Authorization: Bearer pk_live_…`.
- **Origin-locked:** the key only works from the origins it was allow-listed for (e.g.
  `https://*.example.com`). A request from any other origin → **403**. This is the real gate that
  makes it safe to expose the key in page source.
- Rate limited per key (default **100 requests/hour**).
- Read-only: client keys **cannot** ingest or delete (→ **403**).

### Server keys (proxy / backend)

- Sent as `X-Server-Key: sk_live_…`.
- Must **not** be used from a browser: if an `Origin` header is present the request is rejected with
  **400** (a server key in a browser would leak the secret).
- Require an **`X-End-User: <stable id>`** header identifying the end user on whose behalf you're
  calling — rate limits are applied per `(server key, end user)`, so one heavy user can't exhaust
  another's budget.
- Can ingest (`POST /ingest`) and delete (`DELETE /v1/demos/{id}`).

> **Proxy mode.** To embed the viewer without putting any key in the browser, run a thin backend
> proxy that injects `X-Server-Key` + `X-End-User` and forwards `/v1/**` transparently. See
> [VIEWER.md](../viewer/README.md) §Proxy mode and the reference implementations in
> `viewer/examples/`.

### Auth errors

| Status | Meaning |
|---|---|
| `401` | Missing / invalid / expired key |
| `403` | Client-key origin not allowed, **or** a client key used for a write/delete |
| `400` | Server key sent from a browser, or missing `X-End-User` |

---

## Rate limiting

Successful responses carry:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 97
X-RateLimit-Reset: 1718200000        # unix epoch when the window rolls over
```

Over the limit → **429** with `Retry-After: <seconds>`. Back off until then. (A `304 Not Modified`
on a round fetch is **not** counted against the limit.)

---

## CORS

`/v1/**` allows any origin (`Access-Control-Allow-Origin: *`) for `GET`/`OPTIONS` with no
credentials — the client-key origin allowlist is the real gate, so this is safe. `ETag` and the
`X-RateLimit-*` headers are exposed to browser JS.

---

## Ingesting demos

### `POST /ingest`  — submit a demo (or a multi-demo archive)

Backend operation → **server key** + `X-End-User`. Returns immediately (`202`); parsing happens
asynchronously on the worker. Poll `GET /ingest/{job_id}` for completion (or get a webhook).

**Headers**

```
X-Server-Key: sk_live_…
X-End-User: <stable user id>
Idempotency-Key: <optional unique string>      # a retry with the same key returns the same job
Content-Type: application/json
```

**Body**

```json
{
  "source": { "type": "url", "ref": "https://example.com/match.dem" },
  "name": "ENCE vs Vitality — Nuke",
  "refs": [ { "source": "hltv", "external_id": "2378001" } ],
  "webhook_url": "https://you.example/hooks/demo",
  "anonymize": false
}
```

| Field | Required | Notes |
|---|---|---|
| `source.type` | yes | `"url"` — the API downloads it on the worker (SSRF-guarded: private IPs, redirects to private ranges, and oversize downloads are rejected). |
| `source.ref` | yes | The demo URL. Accepts a raw `.dem`, `.gz`, `.zip`, **`.rar`/`.7z`**, and **multi-demo archives** (an HLTV match with one `.dem` per map) and **split parts** (`*_p1.dem` + `*_p2.dem`). |
| `name` | no | Display name. |
| `refs` | no | Your own identifiers (e.g. an HLTV match id). A ref **may map to several demos** — for a multi-demo archive each map gets the ref, so the match id resolves to all maps (disambiguate with `?map=` or use the collections endpoint). |
| `webhook_url` | no | Called (signed) on completion — see [WEBHOOKS.md](WEBHOOKS.md). |
| `anonymize` | no | Replace steamids/names with stable per-demo aliases. |

**Responses**

```jsonc
// 202 — accepted
{ "job_id": "f0e1…", "status": "queued", "lane": "arq:queue" }

// 202 — idempotent replay (same Idempotency-Key) → the original job, not a duplicate
{ "job_id": "f0e1…", "status": "ready", "idempotent": true }

// 429 — the ingest queue is at capacity (backpressure); retry after the header
//   Retry-After: <seconds>
```

**Multi-demo archives.** When the archive holds several demos, they're ingested into a **collection**
(one parse per map) and each demo dedups independently by its content hash — re-submitting a match
re-parses only maps you don't already have. Query the result via the **collections** endpoints below.

### `GET /ingest/{job_id}`  — job status

Any key (the job is owned by its submitter; another tenant gets **404**).

```json
{
  "job_id": "f0e1…",
  "status": "queued | downloading | parsing | ready | failed",
  "demo_id": 1234,
  "progress": { "stage": "payloads", "collection_id": 90, "demo_ids": [1234, 1235] },
  "error": null
}
```

When `status` is `ready`, `demo_id` is the (primary) demo; for a multi-demo archive,
`progress.collection_id` + `progress.demo_ids` list the whole match.

---

## Serving — reading demos

All read endpoints are aggressively cacheable and identical whether called **directly** (client key)
or **via a proxy** (server key). A key may only read demos its tenant owns — anything else returns
**404** (never 403), so ids aren't probeable across tenants.

### `GET /v1/demos`  — list your demos (paginated)

Query params: `cursor` (id to page before), `limit` (1–100, default 50), `map`, `status`.

```json
{
  "items": [
    { "id": 1234, "map": "de_nuke", "name": "…", "status": "ready",
      "round_count": 24, "created_at": "2026-06-10T10:00:00Z",
      "refs": [ { "source": "hltv", "external_id": "2378001" } ] }
  ],
  "next_cursor": 1190
}
```

Page forward with `?cursor=<next_cursor>` until `next_cursor` is `null`.

### `GET /v1/demos/{id}`  — demo metadata + round index

The body the viewer loads first. `Cache-Control: public, max-age=60`.

```jsonc
{
  "id": 1234,
  "map": "de_nuke",
  "name": "ENCE vs Vitality — Nuke",
  "status": "ready",
  "payload_version": 1,
  "round_count": 24,
  "duration_ticks": 230400,
  "refs": [ { "source": "hltv", "external_id": "2378001" } ],
  "players": [ /* optional Steam summaries */ ],
  "rounds": [ { "round_index": 1, "meta": { "winner": "ct", "reason": "bomb_defused",
                                            "CT_score": 1, "T_score": 0, "n_ticks": 2200 } } ],
  "map_ref": { "name": "de_nuke", "pos_x": -3453, "pos_y": 2887, "scale": 7,
               "rotate": null, "zoom": null, "radar_url": "https://…/de_nuke.svg", "levels": [ … ] },
  "map_supported": true,
  "calibration_suspect": false,
  "cdn": null
}
```

- **Not ready yet** → **409** with `{ "status": "parsing", "detail": "poll until status is 'ready'" }`
  (and `Cache-Control: no-store`). Poll until ready.
- **Unsupported map** (community/unknown) → `200` with `map_supported: false` and `map_ref: null`
  (the viewer shows a clean "map not supported" state rather than rendering into a void).
- **`cdn`** — when edge-token serving is enabled, a short-lived signed token block the viewer uses to
  fetch payloads straight from the CDN; `null` otherwise (the viewer falls back to the round endpoint).

### `GET /v1/demos/{id}/rounds/{i}`  — per-round payload

The replay data for one round: **gzipped JSON bytes** (`Content-Encoding: gzip`).

- Immutable: `Cache-Control: public, max-age=31536000, immutable` + a content-stable `ETag`.
- Send `If-None-Match: <etag>` to get **304** with no body (and no rate-limit charge).
- `409` if the demo isn't ready; `404` if the round doesn't exist; `429` if a tenant bandwidth cap is
  exceeded (`Retry-After` set).

The payload shape is `{ ticks, meta, smokes, infernos, kills }` (per-tick player positions, utility,
bomb, weapon fires, and the killfeed). **You normally don't parse this yourself** — the bundle's
worker decodes it into typed arrays. If you do, decode = gunzip → JSON.

### `GET /v1/demos/by-ref/{source}/{external_id}`  — resolve by your own id

Look a demo up by an identifier you attached at ingest. A ref can map to several demos (one per map
of a match) — add **`?map=de_nuke`** to pick one; without it you get the first owned match demo. Same
body as `GET /v1/demos/{id}`. Unknown/unowned → **404**.

```
GET /v1/demos/by-ref/hltv/2378001?map=de_nuke
```

### `GET /v1/collections/by-ref/{source}/{external_id}`  — a whole match

The collection (an ingested multi-demo archive / match) and **all** its map demos — e.g. to build a
map picker for an HLTV match. `GET /v1/collections/{id}` does the same by collection id.

```json
{
  "id": 90,
  "source": "hltv",
  "external_id": "2378001",
  "name": "ENCE vs Vitality",
  "demos": [
    { "id": 1234, "map": "de_nuke",   "name": "…", "status": "ready", "round_count": 24 },
    { "id": 1235, "map": "de_mirage", "name": "…", "status": "ready", "round_count": 19 }
  ]
}
```

### `GET /v1/maps` · `GET /v1/maps/{map}`  — radar calibration

The radar image URL + the world→radar calibration the viewer uses. Reference data,
`Cache-Control: public, max-age=86400`. Unknown map → `404`.

```json
{ "name": "de_nuke", "display_name": "Nuke", "pos_x": -3453, "pos_y": 2887, "scale": 7,
  "rotate": null, "zoom": null, "selections": [ … ], "radar_url": "https://…/de_nuke.svg" }
```

### `DELETE /v1/demos/{id}`  — delete a demo

**Server key** (destructive). Purges all stored artifacts (per-round payloads, index, canonical, cold
raw archive) and the DB rows. Unknown/unowned → `404`. Returns the removed keys.

---

## Webhooks

If you pass `webhook_url` at ingest, completion is delivered as an HMAC-signed, replay-protected,
retried-with-backoff POST. Full signature scheme + verification: [WEBHOOKS.md](WEBHOOKS.md).

```json
{ "event": "demo.ready",  "job_id": "f0e1…", "demo_id": 1234, "status": "ready" }
{ "event": "demo.failed", "job_id": "f0e1…", "demo_id": null, "status": "failed" }
```

---

## Health & metrics

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /healthz` | none | Liveness — `{ "status": "ok" }` |
| `GET /readyz` | none | Readiness — `{ "ready": true, "checks": { "db": "ok", "redis": "ok" } }` (503 if a dep is down) |
| `GET /metrics` | none | Prometheus exposition (request/latency, 429 rate, queue depth, parse time) |
| `GET /v1/whoami` | any key | Echoes your resolved key context — handy to verify auth/rate-limit wiring |

---

## Error reference

| Status | When |
|---|---|
| `400` | Bad request — server key from a browser, missing `X-End-User`, malformed body |
| `401` | Missing/invalid/expired key |
| `403` | Client-key origin denied, or a client key on a write/delete |
| `404` | Demo/round/collection/ref unknown **or** not owned by your tenant |
| `409` | Demo not ready yet (poll); also returned on a round fetch before ready |
| `429` | Rate limit, ingest backpressure, or bandwidth cap — honor `Retry-After` |
| `5xx` | Server error — safe to retry idempotently |

---

## Quick start (server key)

```bash
BASE=https://api.csstrats.dk
SK=sk_live_…

# 1) ingest an HLTV match archive (multi-demo .rar → a collection)
curl -s "$BASE/ingest" \
  -H "X-Server-Key: $SK" -H "X-End-User: web-1" -H "Idempotency-Key: hltv-2378001" \
  -H 'content-type: application/json' \
  -d '{"source":{"type":"url","ref":"https://example.com/2378001.rar"},
       "refs":[{"source":"hltv","external_id":"2378001"}]}'
# → { "job_id": "…", "status": "queued" }

# 2) poll
curl -s "$BASE/ingest/<job_id>" -H "X-Server-Key: $SK" -H "X-End-User: web-1"

# 3) read the match + pick a map
curl -s "$BASE/v1/collections/by-ref/hltv/2378001" -H "X-Server-Key: $SK" -H "X-End-User: web-1"
curl -s "$BASE/v1/demos/by-ref/hltv/2378001?map=de_nuke" -H "X-Server-Key: $SK" -H "X-End-User: web-1"
```

Then embed the viewer pointed at the resolved `demoId` — see [VIEWER.md](../viewer/README.md).
