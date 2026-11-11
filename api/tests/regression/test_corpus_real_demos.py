"""Stage 15 — the `slow` real-demo corpus gate (runs on `main`, when the .dem files are present).

The fast PR gate (test_corpus_golden.py) runs over committed recorded fixtures so it needs no
demos and no awpy. THIS gate closes the loop: when the actual corpus `.dem` files are available
locally (point `DEMO_CORPUS_DIR` at a directory of `<slug>.dem`, or a checkout of the cold-storage
corpus), it re-parses each through the *production* pipeline code and recomputes the snapshot, so a
real awpy/parser/payload regression that the frozen fixtures can't see fails here against the same
golden. Skipped cleanly when the demos aren't present (CI without the corpus, every dev machine).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus.loader import recorded_entries  # noqa: E402

from app.config import settings  # noqa: E402
from app.corpus import build_snapshot, check_ground_truth, diff_snapshot  # noqa: E402

pytestmark = [pytest.mark.regression, pytest.mark.slow]

CORPUS_DIR = os.environ.get("DEMO_CORPUS_DIR")
_entries = recorded_entries()
_ids = [e.slug for e in _entries]


def _demo_path(slug: str) -> Path | None:
    if not CORPUS_DIR:
        return None
    p = Path(CORPUS_DIR) / f"{slug}.dem"
    return p if p.exists() else None


def _record_real_parse(path: str) -> dict:
    """Run the production parse path on a real .dem and assemble the recorded-fixture shape."""
    from app.ingest.calibration import sample_positions
    from app.ingest.pipeline import _default_parse
    from app.ingest.rounds import build_parse_report, build_round_records, frames_from_demo
    from app.ingest.classify import classify_demo

    cls = classify_demo(path)
    dem = _default_parse(path)
    frames = frames_from_demo(dem)
    records = build_round_records(frames)
    report = build_parse_report(cls, frames, records)
    return {
        "parse_report": report,
        "round_metas": [r.light_meta for r in records],
        "sampled_positions": sample_positions(frames.ticks),
    }


@pytest.mark.parametrize("entry", _entries, ids=_ids)
def test_real_demo_matches_golden(entry):
    path = _demo_path(entry.slug)
    if path is None:
        pytest.skip(f"corpus demo for {entry.slug} not present (set DEMO_CORPUS_DIR)")

    if entry.ground_truth.get("rejected"):
        # Rejection cases must be refused by the production guards, never parsed.
        from app.ingest.classify import UnsupportedDemoError, classify_demo
        from app.ingest.errors import IngestError

        with pytest.raises((UnsupportedDemoError, IngestError, Exception)):
            classify_demo(str(path))
        return

    snapshot = build_snapshot(_record_real_parse(str(path)))
    assert not check_ground_truth(entry.ground_truth, snapshot), entry.slug
    diffs = diff_snapshot(entry.load_golden(settings.payload_version), snapshot)
    assert not diffs, (
        f"REAL-demo golden drift for {entry.slug} — a parser/awpy/payload change moved an output:\n  "
        + "\n  ".join(diffs)
    )
