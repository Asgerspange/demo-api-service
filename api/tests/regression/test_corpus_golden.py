"""Stage 15 — the corpus regression harness itself.

These are the tests that make "we keep it working through every CS2 update" provable: each
committed golden must equal the snapshot freshly computed from its recorded fixture (a
parser/payload bump that moves an output fails here with a readable diff), each snapshot must
agree with the manifest's independently-declared ground truth, and the manifest must *cover*
every Stage 11 case + the active-duty map matrix. They run in the normal (not-slow) suite, so
the gate fires on every PR (§15.4). The heavier `slow` path re-parses the real `.dem` files.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests/ → import the corpus loader

from corpus.loader import (  # noqa: E402
    ACTIVE_DUTY_MAPS,
    REQUIRED_CASES,
    load_manifest,
    recorded_entries,
)

from app.config import settings  # noqa: E402
from app.corpus import build_snapshot, check_ground_truth, diff_snapshot  # noqa: E402

pytestmark = pytest.mark.regression

PV = settings.payload_version
RECORDED = recorded_entries()
_ids = [e.slug for e in RECORDED]


@pytest.mark.parametrize("entry", RECORDED, ids=_ids)
def test_recorded_snapshot_matches_golden(entry):
    """The committed golden == build_snapshot(recorded). A drift here is the review surface:
    decide fix-or-regression, then `regen_corpus_goldens.py` after review."""
    snapshot = build_snapshot(entry.load_recorded())
    golden = entry.load_golden(PV)
    diffs = diff_snapshot(golden, snapshot)
    assert not diffs, (
        f"golden drift for {entry.slug} (payload_version {PV}):\n  "
        + "\n  ".join(diffs)
        + "\n→ if intentional, run `uv run python scripts/regen_corpus_goldens.py` and review."
    )


@pytest.mark.parametrize("entry", RECORDED, ids=_ids)
def test_snapshot_consistent_with_ground_truth(entry):
    """The derived snapshot must agree with the human-asserted ground truth (round count, final
    score, roster) — independent of whether the golden was updated."""
    snapshot = build_snapshot(entry.load_recorded())
    issues = check_ground_truth(entry.ground_truth, snapshot)
    assert not issues, f"ground-truth mismatch for {entry.slug}:\n  " + "\n  ".join(issues)


def test_corpus_covers_stage11_cases():
    cases: set[str] = set()
    for e in load_manifest():
        cases.update(e.cases)
    missing = REQUIRED_CASES - cases
    assert not missing, f"corpus is missing Stage 11 cases: {sorted(missing)}"


def test_corpus_covers_active_duty_map_matrix():
    maps = {e.map for e in load_manifest() if e.map}
    missing = ACTIVE_DUTY_MAPS - maps
    assert not missing, f"corpus is missing active-duty maps: {sorted(missing)}"


def test_corpus_has_a_reworked_and_an_unknown_map():
    cases = {c for e in load_manifest() for c in e.cases}
    assert "reworked_map" in cases and "unknown_map" in cases


def test_every_recorded_entry_has_a_golden():
    for e in RECORDED:
        assert e.golden_path(PV).exists(), f"missing golden for {e.slug} — run regen_corpus_goldens.py"


def test_harness_detects_output_drift():
    """The harness's reason to exist: a changed parse output MUST move the snapshot so the golden
    diff catches it. Mutate a recorded value → the snapshot differs (a real regression would too)."""
    entry = next(e for e in RECORDED if e.ground_truth.get("round_count"))
    base = build_snapshot(entry.load_recorded())

    drifted = entry.load_recorded()
    drifted["round_metas"][0]["reason"] = "totally_different_reason"
    after = build_snapshot(drifted)

    diffs = diff_snapshot(base, after)
    assert any("reason" in d for d in diffs), "harness failed to notice a changed round reason"


def test_ground_truth_catches_a_scoreline_regression():
    """An overtime side-switch bug that corrupts the final score is exactly what must fail CI."""
    entry = next(e for e in RECORDED if e.ground_truth.get("final_score"))
    regressed = entry.load_recorded()
    regressed["round_metas"][-1]["CT_score"] += 7  # phantom rounds → wrong final score
    issues = check_ground_truth(entry.ground_truth, build_snapshot(regressed))
    assert any("final_score" in i for i in issues)


def test_rejection_cases_snapshot_as_rejected():
    """POV / CSGO / truncated demos must snapshot as a rejection (a regression that suddenly
    *accepts* one is caught — the snapshot outcome flips)."""
    rejected = [e for e in RECORDED if e.ground_truth.get("rejected")]
    assert rejected, "corpus should pin at least one rejection case"
    for e in rejected:
        snap = build_snapshot(e.load_recorded())
        assert snap["outcome"] == "rejected" and snap["error"], e.slug


def test_overtime_demo_exceeds_regulation():
    e = next(x for x in RECORDED if "overtime" in x.cases)
    snap = build_snapshot(e.load_recorded())
    assert snap["round_count"] > 24
    assert max(snap["final_score"]["CT"], snap["final_score"]["T"]) > 13


def test_disconnect_demo_records_anomaly():
    e = next(x for x in RECORDED if "disconnect" in x.cases)
    snap = build_snapshot(e.load_recorded())
    assert any("players" in a for a in snap["anomalies"]), "disconnect should surface a roster anomaly"


def test_add_reproducer_validates_before_committing():
    """The add-a-reproducer flow's pre-commit check rejects a capture that disagrees with the
    declared ground truth — so a bad reproducer can't land."""
    good = {"rejected": True, "stage": "parse", "error": "unexpected EOF"}
    assert not check_ground_truth({"rejected": True}, build_snapshot(good))

    bad = {"parse_report": {"rounds_found": 5, "players": []},
           "round_metas": [{"round_index": 5, "CT_score": 3, "T_score": 2}],
           "sampled_positions": []}
    issues = check_ground_truth({"round_count": 30}, build_snapshot(bad))
    assert any("round_count" in i for i in issues)
