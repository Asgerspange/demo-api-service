# Stage 18 — Multi-Demo Archives, Collections & Multi-Part Demos

**Goal:** ingest the way demos actually arrive from the wild — a single **archive holding several
demos** (an HLTV match `.rar`/`.zip` with one `.dem` per map), and demos **split into parts**
(`match_p1.dem`, `match_p2.dem`) — and give them a storage + query model where the maps of one match
share an identity yet are addressable individually.

## Context

Stage 05 extraction assumes one container → exactly one `.dem`, rejects `.rar` (the non-free
`unrar`), and `demo_external_refs` is globally unique on `(source, external_id)` so an HLTV match id
can point at only one demo. But:

- **HLTV ships a whole match as one archive** — `.rar` (most common) or `.zip` — containing
  `de_nuke.dem`, `de_mirage.dem`, … one per map played. Today we'd reject the `.rar` and, even as a
  `.zip`, refuse the "multiple `.dem` members".
- **The same match id should resolve to several demos**, picked apart by map: "give me HLTV match
  2378001, map de_nuke".
- **Some sources split a single demo across part files** (`_p1`, `_p2`, …) that must be concatenated
  back into one stream before parsing.

## 18.1 Multi-demo extraction

- `extract_dems()` returns **all** `.dem` members of an archive (not "exactly one"), keeping the
  Stage 05 guards: member-count cap, total + per-member uncompressed-size cap, traversal-safety
  (read by name into memory, never extract-to-disk), magic-byte CS2 validation, CSGO rejection.
- **RAR support via libarchive** (`bsdtar`/`libarchive` — BSD-licensed, reads RAR4 **and** RAR5),
  replacing the non-free `unrar` rejection. Capability-gated: if libarchive isn't present the old
  clean rejection stands (with the "re-upload as .zip" message). 7z rides the same path for free.
- A single-`.dem` container still yields a one-element list, so the existing happy path is unchanged.

## 18.2 Multi-part reassembly

- Detect split parts by filename: a `_pN` / `.partN` / `-pN` suffix on the stem groups files sharing
  a base (`match_p1.dem` + `match_p2.dem` → base `match`). Parts are **sorted by N and concatenated**
  in order into one logical `.dem` (HLTV-style byte continuations: only part 1 carries the `PBDEMS2`
  header, so CS2 validation runs on the **reassembled whole**, not each part).
- Non-part files pass through unchanged. Reassembly runs over the extracted members *before* parsing,
  so a part-split demo inside a multi-demo archive is handled too.

## 18.3 Storage & query model — collections + shared refs

- **`demo_collections`** — one row per ingested archive/match: `(owner, source, external_id, name)`,
  unique on `(owner, source, external_id)` so re-ingesting the same HLTV match attaches to the same
  collection. `demos.collection_id` links each contained demo to it.
- **Shared external ids** — relax `demo_external_refs` from globally-unique `(source, external_id)` to
  **unique per `(demo_id, source, external_id)`** (indexed on `(source, external_id)`), so an HLTV
  match id can point at every map demo of that match. Resolution becomes one-to-many.
- **Query by map** — `GET /v1/demos/by-ref/{source}/{ext}?map=de_nuke` disambiguates to one demo;
  `GET /v1/collections/by-ref/{source}/{ext}` returns the collection + **all** its demos (each with
  its map) so a host can render a match's map picker. Cross-tenant lookups stay 404 (not 403).

## 18.4 Ingest fan-out

- An archive with N demos enqueues **one parse per demo** but groups them under a single collection
  (created once, idempotently). Each demo dedups independently by its own sha256 (re-submitting a
  match whose `de_nuke` you already have re-parses only the new maps). The shared `external_id` is
  attached to the collection; per-demo refs carry the map so by-ref?map resolves cleanly.
- Backpressure/fairness (Stage 16) applies per contained demo, so one fat match archive is scheduled
  fairly against other tenants rather than as one giant job.

## Reuse from existing code

- `app/ingest/extract.py` guards → extended to the multi-member + libarchive path.
- `demo_external_refs` + `RefRepo` (Stage 02) → relaxed uniqueness + `resolve_all`.
- The Stage 16 idempotency + fairness plumbing → per-contained-demo jobs.

## Acceptance criteria

- **Tests (required for Done):** written and green in CI — see `TESTING.md`.

- A multi-demo `.zip` **and** `.rar` (libarchive present) ingest into N demos under one collection;
  the same archive re-submitted dedups per-demo and doesn't duplicate the collection.
- A part-split demo (`*_p1.dem` + `*_p2.dem`, in an archive or as a group) reassembles to one demo
  that parses.
- One HLTV match id resolves to all its map demos; `?map=` (or the collections endpoint) selects one.
- Security guards intact: member-count/size caps, traversal-safety, CSGO rejection, and a clean
  rejection when libarchive is unavailable for `.rar`.
