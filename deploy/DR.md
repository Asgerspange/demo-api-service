# Disaster Recovery & Reliability (Stage 16 §16.3)

The DB holds the demo→object mapping; the bunny parquet/payload/raw archives are useless without
it. This runbook covers backups, the tested restore, the storage-rebuild fallback, vendor risk,
and secrets rotation.

## DB backups + tested restore

- **Backups:** nightly **Percona XtraBackup** (hot, non-blocking) of the `demoviewer` database to a
  bucket in a *different* provider/region than bunny (don't co-locate the backup with the data it
  protects). Keep ≥14 daily + 8 weekly. Also keep a `mysqldump --single-transaction` logical dump
  weekly as a portable, engine-independent fallback.
- **Restore (test quarterly):**
  ```bash
  # physical (fast, full instance)
  xtrabackup --prepare --target-dir=/backups/2026-06-10
  systemctl stop mysql && rsync -a /backups/2026-06-10/ /var/lib/mysql/ && systemctl start mysql
  # logical (single DB)
  mysql -uroot -p demoviewer < demoviewer-2026-06-10.sql
  # then re-apply forward migrations (idempotent) and verify readiness
  cd api && uv run python -m app.storage.migrate   # or the app's migrate entrypoint
  curl -fsS localhost:8000/readyz
  ```
  A restore is **not done** until `GET /readyz` is green and a sampled demo serves end-to-end.
  Record the restore wall-clock each quarter — that's your RTO.

## Rebuild-from-storage (worst case: mapping lost, objects survive)

If the DB and all backups are unrecoverable but the demos zone is intact, re-derive the mapping by
scanning storage (the objects are self-describing via each demo's `index.json`):

```bash
cd api && uv run python scripts/rebuild_from_storage.py --owner <recovery_user_id> [--payload-version 1]
```

This walks the zone, reads each `index.json`, and re-creates the `demos` + `demo_rounds` rows
pointing at the surviving payloads (owned by `--owner`, flagged `meta.rebuilt_from_storage`). The
original `sha256`/owner can't be recovered from storage, so a synthetic sha is used and dedup for
those demos resets — re-ingesting an identical demo afterward will parse once more. Idempotent;
safe to re-run. Logic + idempotency are covered by `tests/integration/test_multitenancy.py`.

## Vendor risk

bunny is a single vendor for **storage + CDN** — a zone loss takes both. Mitigations:
- The **cold raw `.dem`** lives in a separate archive zone (Stage 10); everything (parquet +
  payloads) is re-derivable from it via a Stage 14 **deep** backfill. Keep that zone's keys + a
  copy of its key list off-bunny.
- The geo-replicated served `demos` zone (FRA/LA/NY) survives a single-region loss.
- Keep the DB backup (the mapping) off-bunny so a bunny outage never blocks a DB restore.

## Staging, status page, comms

- **Staging** mirrors prod topology (`deploy/compose.prod.yml` against a staging DB + a separate
  bunny zone) so customers can test integrations without touching prod limits/data.
- **Status page** (external host — not behind the same infra) for `api` / `ingest` / `cdn`, wired to
  the Stage 08 metrics (`/readyz`, queue depth, parse-success rate, 429 rate). Publish incident comms
  there; a Valve-update parse-success dip is an expected, communicable event (Stage 15).

## Secrets rotation runbook

Rotatable secrets and their blast radius:

| Secret | Where | Rotate | Compromise response |
|---|---|---|---|
| `ADMIN_TOKEN` | env | set new value, redeploy api | rotate immediately; audit `/admin` access logs |
| bunny Storage `AccessKey` | env (`BUNNY_*_STORAGE_KEY`) | new key in bunny → env → redeploy | revoke old key in bunny dashboard |
| `BUNNY_DEMOS_TOKEN_KEY` (CDN signing) | env | rotate in bunny → env; old signed URLs expire after `CDN_TOKEN_TTL` | rotate; brief window of valid old tokens until TTL |
| API keys (`pk_/sk_`) | DB (hashed) | owner dashboard → rotate (grace window) or revoke | revoke; cache busts within `KEY_CACHE_TTL` |
| Webhook secret | DB (`users.webhook_secret`) | owner dashboard → reissue the tenant's secret | rotate; tell the customer to update their verifier |
| `STEAM_API_KEY` | env | reissue at Steam → env | low impact (summaries are best-effort) |

On a suspected key compromise: rotate the affected secret first, then audit usage (admin job/usage
endpoints, bunny request logs), then notify any affected tenant.
