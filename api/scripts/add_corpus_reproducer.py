#!/usr/bin/env python
"""Add a production parse failure (or any real demo) to the Stage 15 corpus in minutes (§15.4).

When a real demo fails (or a new format/edge case appears), capture a sanitized reproducer so it
can never regress silently again. This script takes the structured outputs you captured from the
pipeline and (1) writes the recorded fixture, (2) appends a manifest entry with your declared
ground truth, and (3) regenerates that entry's golden — so the next CI run pins the behavior.

Capture input is a JSON file in the recorded-fixture shape:

  parsed:    {"parse_report": {...}, "round_metas": [...], "sampled_positions": [[x,y], ...]}
  rejected:  {"rejected": true, "stage": "classify|extract|parse", "error": "..."}

`parse_report`/`round_metas` are exactly `demos.meta['parse_report']` and the per-round
`light_meta` the pipeline already produces — copy them straight out of a failed job's record
(after scrubbing any PII you don't want committed).

  uv run python scripts/add_corpus_reproducer.py \
      --slug prod-fail-vertigo-2026-06 --map de_vertigo --cases truncated \
      --storage-ref corpus/prod-fail-vertigo-2026-06.dem \
      --ground-truth '{"rejected": true}' \
      --from captured.json

Run from the `api/` directory.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from app.config import settings  # noqa: E402
from app.corpus import build_snapshot, check_ground_truth  # noqa: E402
from corpus.loader import MANIFEST_PATH, RECORDED_DIR  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Add a corpus reproducer.")
    ap.add_argument("--slug", required=True)
    ap.add_argument("--from", dest="src", required=True, help="captured recorded-outputs JSON")
    ap.add_argument("--map", default=None)
    ap.add_argument("--cases", default="", help="comma-separated case tags")
    ap.add_argument("--storage-ref", default=None)
    ap.add_argument("--description", default="")
    ap.add_argument("--ground-truth", default="{}", help="JSON ground-truth assertion")
    args = ap.parse_args()

    recorded = json.loads(Path(args.src).read_text(encoding="utf-8"))
    ground_truth = json.loads(args.ground_truth)

    # Validate against the declared ground truth BEFORE committing, so a bad capture is caught now.
    snapshot = build_snapshot(recorded)
    issues = check_ground_truth(ground_truth, snapshot)
    if issues:
        print("ground-truth check failed (fix the capture or the ground truth):")
        for i in issues:
            print(f"  - {i}")
        return 1

    # 1. Recorded fixture.
    RECORDED_DIR.mkdir(parents=True, exist_ok=True)
    (RECORDED_DIR / f"{args.slug}.json").write_text(
        json.dumps(recorded, indent=2) + "\n", encoding="utf-8")

    # 2. Manifest entry (skip if the slug already exists).
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if any(e["slug"] == args.slug for e in manifest["demos"]):
        print(f"manifest already has slug {args.slug!r}; updated the fixture + golden only.")
    else:
        manifest["demos"].append({
            "slug": args.slug,
            "description": args.description or f"Reproducer {args.slug}",
            "map": args.map,
            "cases": [c.strip() for c in args.cases.split(",") if c.strip()],
            "storage_ref": args.storage_ref,
            "recorded": True,
            "ground_truth": ground_truth,
        })
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    # 3. Golden.
    golden = ROOT / "tests" / "corpus" / "golden" / f"v{settings.payload_version}" / f"{args.slug}.json"
    golden.parent.mkdir(parents=True, exist_ok=True)
    golden.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"added corpus reproducer {args.slug!r}: fixture + manifest entry + golden written.")
    print("Upload the sanitized .dem to cold storage at the storage_ref, then commit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
