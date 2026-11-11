# Security & threat model (Stage 08 §8.2)

The hardening audit, as a living document. Most items are enforced by tests
(`tests/unit/test_ssrf.py`, `test_extract.py`, `test_hardening.py`, `tests/e2e/test_delete.py`,
and the auth/origin tests from Stage 03/04).

## Ingestion (attacker-controlled input)

- **SSRF** — `app/ingest/security.py` rejects private/loopback/link-local/CGNAT/reserved/
  metadata IPs and non-http(s) schemes *before* any connection; the downloader disables
  redirects (a 30x to an internal host is refused) and caps bytes + time. **The connection is
  pinned to the validated IP** (`acquire._pin_to_ip`): we resolve+vet once, then dial that exact
  IP with the original `Host` header and TLS SNI (`sni_hostname`), so a DNS rebind can't swap in
  an internal address between the check and the connect (TOCTOU). Tested: `test_ssrf.py` (private
  literals, redirect refusal, size cap, pre-connect block, **IP pinning**).
- **Ingestion is server-key-only** — `POST /ingest` requires a secret server key
  (`require_server_key`), so a scraped public client key can't submit URLs — shrinking the SSRF
  entry surface to the customer's own backend.
- **Decompression bombs** — `app/ingest/extract.py` caps gzip output, rejects zips with too
  many members or oversized declared sizes, and rejects rar (unsupported). Tested:
  `test_extract.py`.
- **Path traversal** — zip members are read **by name into memory**, never extracted to disk,
  so `../` / absolute member names cannot write outside a directory. Tested: `test_hardening.py`.
- **Format spoofing** — format is detected by **magic bytes**, not extension; the inner payload
  must be a CS2 `.dem` (`PBDEMS2`); CSGO/source1 (`HL2DEMO`) is rejected.
- **`path` intake** is admin/owner-only (debug) — a customer key alone gets 403.

## Auth, keys, origins

- **Keys hashed at rest** (`app/auth/keys.py`); raw key shown once at issuance, never stored
  or logged. Admin token compared in constant time.
- **Client-key origin lock** (`app/auth/origins.py`) — host-only match with `*.domain` wildcards;
  a bare `*` is **not** a wildcard. Treat the `Origin` header as **defense-in-depth**: a
  determined non-browser client can spoof it, so the real protections against a leaked public
  key are (a) the per-key **rate cap** and (b) per-tenant ownership scoping. Document/limit blast
  radius accordingly; rotate a leaked key.
- **Server keys never reach a browser** — a server key presented with an `Origin` header → 400.
- **Writes/destructive ops are server-key-only** — `POST /ingest` and `DELETE /v1/demos/{id}`
  require the secret server key (`require_server_key`); public client keys are read-only. A client
  key (visible in an embed) can never enqueue work or delete a demo.
- **Cross-tenant isolation** — unowned/unknown demo or `by-ref` returns **404, not 403**, so ids
  aren't probeable across tenants (serving + delete).

## Transport / secrets

- **TLS never disabled** — the old Steam `verify=False` is fixed (verification ON); enforced by a
  test that greps `app/` for disabled verification.
- **Secrets in env only** — never in the image or git (`.gitignore` covers `.env*`); prod fails
  fast if the bunny keys or a real `ADMIN_TOKEN` are missing.
- **CORS** — `/v1` is wildcard-CORS **by design**: the embeddable viewer runs on arbitrary
  customer origins and reads with a Bearer client key (no cookies, `allow_credentials=False`).
  The security gate is the client key's **origin allowlist** (enforced in `authenticate()`), not
  CORS. There is no cookie/session to steal via a wildcard here. Admin endpoints are token-gated
  and not browser-embedded.

## Limits

- Ingestion: byte cap (`MAX_DEMO_BYTES`), download timeout, parse timeout, zip member cap,
  bounded per-worker parses (`max_jobs`) + upload concurrency.
- Serving: read-only, I/O-only (object store + Redis), no parsing on the request path.

## Content access control & anti-abuse (Stage 13)

- **Payload scraping/hotlinking** — per-round payloads are served from the CDN edge, which bypasses
  API auth. Closed with bunny **Token Authentication**: the API mints a short-TTL per-demo directory
  token (`app/serving/cdn.py`) into the metadata *after* auth+origin+rate-limit; the edge rejects
  unsigned/expired requests. Keys can stay immutable (the token, not obscurity, is the gate). Enable
  Token Authentication on the pull zone + allow the viewer origin in bunny CORS at deploy.
- **Bandwidth abuse** — per-tenant windowed byte cap (`app/bandwidth.py`) enforced on the round
  endpoint → 429. Cap value is config (`BANDWIDTH_CAP_BYTES`, default unlimited).
- **Steam-ID privacy** — the `anonymize` ingest flag rewrites steamids+names to stable per-demo
  aliases at payload-build time (`app/ingest/privacy.py`); Steam summaries are suppressed.

## Data lifecycle

- **Deletion is complete + verifiable** — `app/lifecycle.delete_demo` purges every object across
  all three tiers (hot per-round + index, warm canonical.zip, cold raw archive) and the DB rows
  (rounds + refs cascade; ingest_jobs pointer cleared first), and returns the removed keys.
  Tested end-to-end (`test_delete.py`). `DELETE /v1/demos/{id}` is owner-scoped.

## Pre-launch

- Run the repo's `/security-review` over `api/` and `viewer/` before launch and triage any
  high-severity findings here.
