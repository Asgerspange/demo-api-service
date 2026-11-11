# Test Corpus & Regression Harness (Stage 15)

The safety net for the parser-maintenance treadmill: a pinned demo corpus + golden outputs so a
Valve update, an `awpy`/`demoparser2` bump, or a payload/renderer change that moves an output
**fails CI with a diff** instead of silently reaching customers.

## What's version-controlled

Demos are large, so the repo holds **pointers + ground truth**, not the `.dem` files:

```
api/tests/corpus/
  manifest.json            # one entry per corpus demo: storage_ref pointer, case tags, ground_truth
  recorded/<slug>.json     # sanitized structured outputs from a real ingest (committable, tiny)
  golden/v<pv>/<slug>.json # the canonical snapshot derived from the recorded fixture, per payload_version
  loader.py                # loads the manifest + fixtures + goldens
viewer/tests/
  render.test.js           # deterministic draw-op transcripts (visual regression, §15.3)
  __snapshots__/           # the committed render snapshots
```

A **snapshot** (`app/corpus.py::build_snapshot`) reduces the structured outputs the pipeline already
emits — `build_parse_report` + per-round `light_meta` + `sample_positions` — to a small, sorted,
deterministic dict: round count, final score, per-round winner/reason/score, player roster, anomalies,
and a coordinate fingerprint. Rejections (POV/CSGO/truncated) snapshot as `{"outcome":"rejected",…}`.

## Coverage (§15.1)

The manifest covers every Stage 11 case — `gotv`, `128tick`, `pro`, `overtime`, `pov`, `truncated`,
`disconnect` — plus the **active-duty map matrix** (de_ancient/anubis/cache/dust2/inferno/mirage/nuke/
overpass), a **reworked** map (de_train), and a **community/unknown** map (de_rats1337). The
`test_corpus_covers_*` tests fail if the manifest and these pools drift apart.

## The two CI gates

- **Fast (every PR)** — `uv run pytest -m "not slow"` runs `tests/regression/test_corpus_golden.py`:
  each committed golden must equal `build_snapshot(recorded)` (a moved output → readable diff), each
  snapshot must agree with the manifest's independently-declared ground truth, and the corpus must
  cover the cases/maps above. `viewer` `npm test` runs the render-transcript snapshots. A golden
  staleness check (`scripts/regen_corpus_goldens.py --check`) blocks an un-regenerated golden.
- **Real demos (`main` / nightly)** — `tests/regression/test_corpus_real_demos.py` (marked `slow`):
  when `DEMO_CORPUS_DIR` points at the actual `<slug>.dem` files, it re-parses each through the
  production pipeline and re-checks the golden — the genuine awpy/parser gate. Skipped when absent.

**Block merge on an unreviewed golden or snapshot diff.** A diff is the decision point: *fix or
regression?* If it's an intended change, regenerate the golden / update the render snapshot in the
same PR so the change is reviewed.

## Adding a reproducer when a real demo fails (§15.4)

A production parse failure (or any new edge case) becomes a permanent regression test in minutes:

1. Capture the failed job's structured outputs into a JSON file (the `recorded` shape):
   - parsed: `{"parse_report": …, "round_metas": […], "sampled_positions": [[x,y],…]}` — copy
     `demos.meta['parse_report']` and the per-round `light_meta` straight out (scrub any PII first);
   - rejected: `{"rejected": true, "stage": "classify|extract|parse", "error": "…"}`.
2. Register it (writes the fixture + manifest entry + golden, validating against your ground truth):
   ```
   cd api && uv run python scripts/add_corpus_reproducer.py \
     --slug prod-fail-vertigo-2026-06 --map de_vertigo --cases truncated \
     --storage-ref corpus/prod-fail-vertigo-2026-06.dem \
     --ground-truth '{"rejected": true}' --from captured.json
   ```
3. Upload the sanitized `.dem` to cold storage at the `storage_ref`, then commit. The next CI run
   pins the behavior forever.

Track **prod parse-success rate** (Stage 08 metrics, `ingest_jobs_outcome_total`); a dip after a
Valve update is the signal to pull a fresh failing demo into the corpus and patch.

## Regenerating

```
cd api
uv run python scripts/gen_corpus_fixtures.py        # rewrite the synthetic stand-in fixtures from specs
uv run python scripts/regen_corpus_goldens.py        # rewrite goldens from recorded fixtures (after review)
uv run python scripts/regen_corpus_goldens.py --check # CI: fail if a committed golden is stale
```

For the viewer render snapshots, review the diff and run `npm test -- -u` to accept an intended change.
