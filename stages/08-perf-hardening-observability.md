# Stage 08 — Performance, Hardening & Observability

**Goal:** make it fast, safe, and operable. Mostly verification and tightening over the
foundations laid in 01–07.

## 8.1 Performance

- **Serving:** confirm per-round payloads are served `immutable` + ETag and cached by CDN;
  measure cache hit ratio. A warm round should never touch the origin twice.
- **Payload size:** compare v1 (gzipped JSON) vs v2 (server-side columnar binary) on real
  demos — bytes over the wire and worker decode time. Adopt v2 where it wins.
- **Parse throughput:** benchmark worker parse time per demo; size the worker pool to CPU.
  Keep parsing off the API event loop entirely (it already is, via arq).
- **API latency:** the read path should be I/O only (object store + Redis); no parsing, no
  pandas. p99 for `/v1/demos/{id}` and `/rounds/{i}` under load target (define a number).
- **Viewer:** profile memory across a full match (Stage 07 §7.3); verify bounded footprint,
  no per-frame allocations, smooth playback at 1x–8x. Test DPR/retina and small containers.
- **Load test:** drive `/v1/**` with k6/locust at expected concurrency; watch Redis limiter
  overhead and DB connection pool saturation (the old pool maxed at 50 — tune).

## 8.2 Hardening / security review

- Re-audit **SSRF** on ingestion (Stage 05 §5.3): private ranges, redirects, metadata IPs.
- Verify **client-key origin locking** can't be bypassed (spoofed `Origin`? rely on it only
  as defense-in-depth alongside the rate cap; document the threat model).
- Confirm **server keys never reach a browser** and `path` ingestion is owner-only.
- Validate **zip/rar extraction** against zip-bombs and path traversal (`../` members).
- Fix the old **`verify=False`** Steam call; never disable TLS verification anywhere.
- Secrets: keys hashed at rest, admin token strong, no secrets in logs.
- Set sane body/size/time limits on every endpoint; add per-scope concurrency caps.
- CORS: only the client key's `allowed_origins`, nothing wildcard in prod.
- Run the repo's `/security-review` over the new `api/` and `viewer/` before launch.

## 8.3 Observability

- **Structured logs** (loguru, already in use) with request id + key id + demo id.
- **Metrics**: request rate, p50/p99 latency, 429 rate per key, queue depth, parse time,
  parse failure rate, object-store error rate, CDN hit ratio. Export Prometheus or push to
  your stack.
- **Error tracking**: capture parse failures with the demo hash + stage so you can replay.
- **Job visibility**: surface `ingest_jobs` status in the admin (Stage 03) — what's queued,
  parsing, failed, with the error.
- **Usage rollups**: daily per-key / per-end-user counts for the admin + future billing.

## 8.4 Data lifecycle

- Retention/delete: "delete my demo" removes DB rows + all object-store keys (canonical +
  per-round). Make deletion complete and verifiable (gap #16).
- Orphan cleanup: periodic sweep for object keys with no DB row and failed-job temp data
  (port the spirit of `demo_service.cleanup_chunks`).

## Acceptance criteria

- **Tests (required for Done):** the tests this phase needs are written and green in CI — see
  `TESTING.md` for stack/layout and its per-phase table for exactly what to cover.

- Load test meets the chosen p99 targets with CDN warm; limiter overhead negligible.
- Viewer memory stays bounded across a full match; no leak across many round switches.
- Security review passes with no high-severity findings (SSRF, key exposure, extraction).
- Dashboards show queue depth, parse time, 429 rate, and CDN hit ratio.
- Demo deletion provably removes every associated object and row.
