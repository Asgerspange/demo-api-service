# Stage 16 — Multi-Tenancy, Fairness & Platform Hardening

**Goal:** behave well under many tenants and load, and be operable as a real B2B service.

## Context

The serving path is async and CDN-fronted, but ingestion is a shared, expensive queue. One
customer dumping 500 post-event demos must not delay another customer's single demo. Plus the
standard platform-reliability gaps.

## 16.1 Queue fairness & priority

- **Priority lanes**: live ingest > backfill (Stage 14); within live, optional tiers
  (enterprise > standard > free). arq supports multiple queues — route by tenant tier.
- **Per-tenant fairness** within a lane: round-robin / weighted scheduling so one tenant's
  bulk batch can't monopolize workers. Cap concurrent in-flight parses per tenant.
- **Backpressure**: a queue-depth ceiling → new ingests get `429` / `Retry-After` (or a
  queued-but-delayed status) instead of unbounded growth.

## 16.2 Idempotency & webhooks

- **Idempotency keys** on `POST /ingest` (beyond sha256 dedup) so client retries don't create
  duplicate jobs; same key → same `job_id`.
- **Webhook security**: HMAC-sign payloads (shared secret per user), include a timestamp and
  nonce (replay protection), and **retry with backoff** on non-2xx with a dead-letter after N
  attempts. Document the signature scheme for customers.

## 16.3 Reliability & DR

- **DB backups** (Percona/XtraBackup) + tested restore. The DB holds the demo→object mapping;
  without it the parquet/raw archives are orphaned. Document the **rebuild path** (re-derive
  the mapping by scanning storage keys if ever needed).
- **Vendor risk**: bunny is a single point for storage+CDN — note the exposure; keep the cold
  raw `.dem` somewhere you could re-derive everything from if a zone is lost.
- **Status page** for customers + incident comms. **Staging environment** customers can test
  against without touching prod limits/data.
- **Secrets rotation** runbook (keys, storage AccessKeys, webhook secrets) and a
  key-compromise response.

## Reuse from existing code

- `demo_service.py` queue lifecycle → reshape into prioritized arq queues.
- `demoparser/Dockerfile`, `compose-example.yml` → staging topology.

## Acceptance criteria

- **Tests (required for Done):** the tests this phase needs are written and green in CI — see
  `TESTING.md` for stack/layout and its per-phase table for exactly what to cover.

- A tenant enqueueing 500 demos does not delay another tenant's single demo (measured).
- Queue-depth ceiling sheds new work gracefully with a clear status, no unbounded growth.
- Duplicate `POST /ingest` with the same idempotency key returns the same job, once.
- Webhooks are HMAC-signed, replay-resistant, and retried with backoff to a dead-letter.
- A documented, tested DB restore; a documented rebuild-from-storage path.
