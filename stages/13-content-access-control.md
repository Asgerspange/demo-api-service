# Stage 13 — Content Access Control & Anti-Abuse

**Goal:** stop free scraping/hotlinking of demo payloads, protect bandwidth, and support
privacy. Closes the biggest hole in the current design.

## Context

Stage 06 returns **CDN URLs** that the browser fetches directly from bunny, so those
requests **bypass the API's auth, origin-lock, and rate limiter**. With immutable, guessable
keys (`demos/{id}/v1/round-3.bin`) anyone who sees one embed can scrape a customer's whole
demo library, and non-customers can hotlink your content. Client-key origin-locking only
protects the metadata call. Fix the payload path.

## 13.1 Token-authenticated payload URLs (primary)

- Use **bunny Token Authentication** on the `demos` pull zone. The API mints a **signed,
  short-TTL URL** for each round payload (or a per-demo prefix token) *after* it has run
  auth + origin-lock + rate-limit. The CDN rejects unsigned/expired requests.
- Viewer flow becomes: `GET /v1/demos/{id}` → metadata includes either pre-signed round URLs
  or a per-demo token + URL template the worker uses. Tokens are scoped (demo + expiry),
  cheap to mint, and never reusable across demos.
- Keep keys **unguessable anyway** (random component in the path) as defense-in-depth.

## 13.2 Referer / origin enforcement at the edge (secondary)

- Configure bunny **referer allowlisting** per pull zone where feasible, mirroring the client
  key's `allowed_origins`. Defense-in-depth only — `Referer` is spoofable — but it stops
  casual hotlinking.

## 13.3 Bandwidth / abuse protection

- Per-key and per-tenant **bandwidth caps** (a viral demo on a tiny customer must not run up
  unbounded egress). Track bytes served per key in Redis; alert/throttle on breach. (The cap
  *values* are a money decision, deferred; the *enforcement mechanism* is built here.)
- Concurrency caps per scope (already in Stage 04) extend to payload minting.

## 13.4 Steam-ID privacy toggle

- Steam IDs are personal data and are currently exposed to every embed. Add a per-demo (or
  per-key) **anonymize** flag that replaces steamids with opaque per-demo aliases in payloads
  and metadata. Supports privacy-sensitive orgs and GDPR posture (full legal handling is
  separate). Anonymization happens at payload-build time (Stage 05) and must be stable within
  a demo.

## 13.5 Signed embeds (optional)

- For high-value content, an optional **signed embed token** the host site generates so only
  authorized pages can initialize the viewer for a given demo — beyond origin-lock. Useful
  for paywalled/private demos.

## Reuse from existing code

- Stage 03 origin-lock + Stage 04 limiter → reuse for the mint step.
- `CacheService.php` intent → token/edge caching considerations.

## Acceptance criteria

- **Tests (required for Done):** the tests this phase needs are written and green in CI — see
  `TESTING.md` for stack/layout and its per-phase table for exactly what to cover.

- A round payload URL without a valid token (or expired) → 403 at the CDN; with a freshly
  minted token → 200.
- Guessing `demos/{id}/v1/round-i.bin` does not return content.
- A per-tenant bandwidth cap, once exceeded, throttles further payload minting.
- The privacy toggle yields payloads with no real steamids, stable aliases within a demo.
- Immutable caching still works for authorized fetches (token TTL ≥ practical session).
