"""Stage 15 — unit tests for the pure corpus snapshot/diff logic (`app/corpus.py`)."""
import pytest

from app.corpus import build_snapshot, check_ground_truth, diff_snapshot

pytestmark = pytest.mark.unit


def test_diff_identical_is_empty():
    a = {"x": [1, 2, {"y": 3}], "z": "ok"}
    assert diff_snapshot(a, dict(a)) == []


def test_diff_points_at_the_exact_field():
    base = {"rounds": [{"reason": "bomb_defused"}]}
    other = {"rounds": [{"reason": "time_ran_out"}]}
    diffs = diff_snapshot(base, other)
    assert diffs == ["rounds[0].reason: 'bomb_defused' != 'time_ran_out'"]


def test_diff_reports_length_and_missing_keys():
    assert any("length" in d for d in diff_snapshot([1, 2], [1]))
    assert any("<missing>" in d for d in diff_snapshot({"a": 1}, {"a": 1, "b": 2}))


def test_build_snapshot_parsed_is_deterministic_and_sorted():
    recorded = {
        "parse_report": {
            "map": "de_x", "demo_type": "gotv", "is_gotv": True, "tickrate": 64,
            "rounds_found": 2, "player_count": 2, "anomalies": ["b", "a"],
            "players": [{"steamid": "2", "name": "z"}, {"steamid": "1", "name": "a"}],
        },
        "round_metas": [
            {"round_index": 2, "winner": "t", "CT_score": 1, "T_score": 1},
            {"round_index": 1, "winner": "ct", "CT_score": 1, "T_score": 0},
        ],
        "sampled_positions": [[1.4, 2.6], [3.0, 4.0]],
    }
    snap = build_snapshot(recorded)
    assert snap["outcome"] == "parsed"
    assert snap["round_count"] == 2
    assert snap["final_score"] == {"CT": 1, "T": 1}        # from the last round by index
    assert snap["rounds"][0]["round_index"] == 1           # rounds sorted
    assert snap["players"][0]["steamid"] == "1"            # roster sorted
    assert snap["anomalies"] == ["a", "b"]
    assert snap["sampled_positions"][0] == [1, 3]          # rounded to ints


def test_build_snapshot_rejected_passthrough():
    snap = build_snapshot({"rejected": True, "stage": "classify", "error": "POV"})
    assert snap == {"snapshot_schema": snap["snapshot_schema"], "outcome": "rejected",
                    "stage": "classify", "error": "POV"}


def test_ground_truth_final_score_is_side_agnostic():
    snap = build_snapshot({
        "parse_report": {"rounds_found": 1, "players": []},
        "round_metas": [{"round_index": 1, "CT_score": 16, "T_score": 19}],
        "sampled_positions": [],
    })
    # swapped labels still match (a side-labeling convention shouldn't matter)...
    assert check_ground_truth({"final_score": {"CT": 19, "T": 16}}, snap) == []
    # ...but a genuinely wrong number fails.
    assert check_ground_truth({"final_score": {"CT": 19, "T": 17}}, snap)
