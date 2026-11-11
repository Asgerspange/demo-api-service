# Storage tiering & cost-per-demo (Stage 10)

Three artifacts per demo, each in the cheapest place that still meets its read frequency. The
**raw `.dem` is the source of truth**; the parquet is a warm CPU-saving cache; the per-round
payloads are the hot, viewer-facing derivative. Physically this is **two zones**: the served
`demos` zone (geo-replicated FRA/LA/NY + CDN in EU/NA — only the payloads + index) and the cheap
cold zone (FRA/Stockholm, no CDN — canonical.zip **and** the raw .dem, the reprocess artifacts).

| Tier | Artifact | Object key | Typical size¹ | Storage zone | Read pattern |
|------|----------|-----------|---------------|--------------|--------------|
| **Hot** | per-round payloads + `index.json` | `demos` zone `{id}/v{pv}/round-*.bin`, `index.json` | ~40 MB (24 rounds, gzip-6) | `demos` zone — geo-repl FRA/LA/NY + CDN | constant (viewer) |
| **Warm** | `canonical.zip` (parquet) | **archive** zone `{id}/canonical.zip` | ~10–20 MB | cold zone (FRA/Stockholm) | occasional (payload re-derive) |
| **Cold** | compressed raw `.dem` | archive zone `{id}/raw.dem.zst` | ~350 MB² | cold zone (FRA/Stockholm) | rare (re-parse) |

¹ For a ~570 MB GOTV de_inferno demo (24 rounds). Scales with match length + player count.
² **Divergence from the plan:** the plan assumed `zstd --ultra -22 --long=31` → ~3–5× (≈120 MB).
  In practice CS2 demos are high-entropy and compress only ~1.6× at *any* level, while `-22` cost
  *minutes* of CPU per demo. We use a **fast multithreaded level** (`INGEST_ARCHIVE_ZSTD_LEVEL`,
  default 10) → ~350 MB but seconds, off the critical path. Tune higher if cold-storage GB cost
  dominates CPU cost for you.

## Cost model

Per-demo monthly storage ≈ `size_GB × $/GB/month × replicas`. The served `demos` zone is
geo-replicated across **3 regions** (FRA/LA/NY) + CDN; the cold zone is **2 regions** (FRA/Stockholm),
cheap, no CDN.

| Tier | size | replicas | ≈ $/demo/month |
|------|------|----------|----------------|
| Hot (payloads)   | 0.04 GB  | ×3 (geo-repl + CDN) | ~$0.0024 |
| Warm (canonical) | 0.015 GB | ×2 (cold zone) | ~$0.0003 |
| Cold (raw)       | 0.35 GB  | ×2 (cold zone) | ~$0.0070 |
| **Total** | | | **≈ $0.01 / demo / month** |

Plus **CDN egress** on the hot tier (viewer reads) — the dominant variable cost at scale, but
mostly absorbed by the pull-zone cache (a warm round never re-hits origin). The cold zone has no
CDN and near-zero egress.

**Why the canonical.zip lives in the cold zone (with the raw), not the served `demos` zone:** the
`demos` zone is geo-replicated across 3 regions and CDN-fronted — that cost is justified only for
bytes the viewer actually fetches. The canonical.zip is **never served** (read only on backfills),
so paying 3× replication + CDN provisioning for it is waste. It belongs in the cheap 2-region cold
zone next to the raw `.dem` — both are reprocess-only artifacts. (Fine here because the cold zone is
plain edge storage, not deep archive, so backfill reads stay fast.)

## Retention

`demos.retention_tier` (`standard|archive|ephemeral`) is the lever for lifecycle policy (keep raw
long for paid tenants, drop for free/ephemeral) — mechanism in place, policy is Stage 14+. Deletion
(`DELETE /v1/demos/{id}`) purges **all three tiers** + DB rows and is tested end-to-end.
