#!/usr/bin/env python
"""(Re)write the Stage 15 golden snapshots from the committed recorded fixtures.

A golden is the canonical `build_snapshot(recorded)` output, stored per `payload_version` so a
format bump is an intentional, reviewed change (§15.2). Run this whenever you intentionally
change the snapshot logic or a recorded fixture; CI then fails if the committed goldens don't
match — the diff is the review surface ("fix or regression?").

    uv run python scripts/regen_corpus_goldens.py            # write goldens for the current PV
    uv run python scripts/regen_corpus_goldens.py --check    # exit 1 if any golden is stale (CI)

Run from the `api/` directory.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from app.config import settings  # noqa: E402
from app.corpus import build_snapshot, diff_snapshot  # noqa: E402
from corpus.loader import recorded_entries  # noqa: E402


def main() -> int:
    check = "--check" in sys.argv
    pv = settings.payload_version
    stale = 0
    for entry in recorded_entries():
        snapshot = build_snapshot(entry.load_recorded())
        path = entry.golden_path(pv)
        text = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
        if check:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != text:
                stale += 1
                print(f"STALE golden: {path.relative_to(ROOT)}")
                if path.exists():
                    for line in diff_snapshot(json.loads(current or "{}"), snapshot):
                        print(f"   {line}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path.relative_to(ROOT)}")
    if check and stale:
        print(f"\n{stale} golden(s) stale — run `uv run python scripts/regen_corpus_goldens.py` "
              f"and review the diff.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
