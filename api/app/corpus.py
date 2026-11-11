"""Test-corpus snapshot logic — the heart of the Stage 15 regression harness.

Valve breaks the demo format on updates; awpy/demoparser2 get patched; our `_player_props`
and payload code shift. Without a pinned corpus and golden outputs, every update is roulette
and regressions reach customers silently. This module turns the structured outputs the
ingestion pipeline already produces (`build_parse_report` + per-round `light_meta` +
`sample_positions`) into a small, deterministic **snapshot** that can be committed as a golden
file and diffed in CI. A parser/awpy bump that changes a snapshot fails the build with a
readable diff — a human then decides "fix or regression" (Stage 15 §15.2).

The functions here are pure (no I/O) so they run in unit CI and so the same snapshot can be
recomputed from a recorded fixture (committable) OR from a live parse of a real corpus demo
(the `slow` path, when the .dem files are present). `manifest.py`-style loading lives in
`tests/corpus`; this module is just the canonicalization + diff + ground-truth logic.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

# Bump only when the snapshot *shape* changes intentionally (independent of payload_version).
SNAPSHOT_SCHEMA = 1

# How many sampled positions to keep in a snapshot (a stable spread, rounded to ints so float
# jitter from a parser/pandas bump that doesn't actually move players can't flap the golden).
SNAPSHOT_POSITION_SAMPLES = 12


def _round_meta(r: Mapping[str, Any]) -> dict[str, Any]:
    """The per-round fields that matter for regression (from `RoundRecord.light_meta`)."""
    return {
        "round_index": int(r["round_index"]),
        "winner": r.get("winner"),
        "reason": r.get("reason"),
        "reason_label": r.get("reason_label"),
        "CT_score": r.get("CT_score"),
        "T_score": r.get("T_score"),
        "n_ticks": r.get("n_ticks"),
    }


def _canon_positions(positions: Sequence[Any] | None) -> list[list[int]]:
    """Down-sample + integer-round world positions to a stable, comparable fingerprint.

    Accepts either a list of (x, y) pairs (`sample_positions` output) or a pre-canonicalized
    list of [x, y] ints (a recorded fixture). Rounding to ints absorbs sub-unit float drift
    while still catching a real calibration/coordinate regression.
    """
    if not positions:
        return []
    step = max(1, len(positions) // SNAPSHOT_POSITION_SAMPLES)
    out: list[list[int]] = []
    for pt in list(positions)[::step][:SNAPSHOT_POSITION_SAMPLES]:
        x, y = (pt[0], pt[1]) if not isinstance(pt, Mapping) else (pt["x"], pt["y"])
        if x is None or y is None:
            continue
        out.append([int(round(float(x))), int(round(float(y)))])
    return out


def build_snapshot(recorded: Mapping[str, Any]) -> dict[str, Any]:
    """Canonicalize one corpus demo's recorded outcome into its golden snapshot.

    `recorded` is the structured result the pipeline produced for the demo, in one of two shapes:

    - **parsed** — `{"parse_report": {...}, "round_metas": [...], "sampled_positions": [...]}`,
      exactly the objects `build_parse_report`, each `RoundRecord.light_meta`, and
      `sample_positions` emit. This is what a successful ingest yields.
    - **rejected** — `{"rejected": true, "stage": "classify"|"extract", "error": "..."}` for the
      cases that must be refused before/without a parse (POV, CSGO, truncated/corrupt) — the
      "snapshot" of a rejection is the rejection itself, so a regression that suddenly *accepts*
      one of those demos (or rejects it for a different reason) is caught too.

    Both shapes are reduced to a small, sorted, deterministic dict suitable for a golden file.
    """
    if recorded.get("rejected"):
        return {
            "snapshot_schema": SNAPSHOT_SCHEMA,
            "outcome": "rejected",
            "stage": recorded.get("stage"),
            "error": recorded.get("error"),
        }

    report = recorded.get("parse_report") or {}
    round_metas = sorted(recorded.get("round_metas") or [],
                         key=lambda r: int(r["round_index"]))
    final = round_metas[-1] if round_metas else {}

    # Roster as a sorted, de-duplicated (steamid, name) set — order-independent.
    roster = sorted(
        {(str(p["steamid"]), p.get("name") or "") for p in report.get("players", [])}
    )

    return {
        "snapshot_schema": SNAPSHOT_SCHEMA,
        "outcome": "parsed",
        "map": report.get("map"),
        "demo_type": report.get("demo_type"),
        "is_gotv": report.get("is_gotv"),
        "tickrate": report.get("tickrate"),
        "round_count": report.get("rounds_found"),
        "final_score": {"CT": final.get("CT_score"), "T": final.get("T_score")},
        "player_count": report.get("player_count"),
        "players": [{"steamid": s, "name": n} for s, n in roster],
        "rounds": [_round_meta(r) for r in round_metas],
        "anomalies": sorted(report.get("anomalies") or []),
        "sampled_positions": _canon_positions(recorded.get("sampled_positions")),
    }


# --- diffing + ground-truth ------------------------------------------------------------

def diff_snapshot(expected: Any, actual: Any, *, path: str = "") -> list[str]:
    """Deep-diff two snapshots, returning human-readable `path: expected != actual` lines.

    Used by the regression test (golden vs freshly-computed) and the add-a-reproducer flow.
    Empty list ⇒ identical. Dict keys and list indices are walked so a diff points at the exact
    field that moved (e.g. `rounds[11].reason: 'bomb_defused' != 'time_ran_out'`).
    """
    diffs: list[str] = []
    if isinstance(expected, Mapping) and isinstance(actual, Mapping):
        for key in sorted(set(expected) | set(actual)):
            sub = f"{path}.{key}" if path else str(key)
            if key not in expected:
                diffs.append(f"{sub}: <missing> != {actual[key]!r}")
            elif key not in actual:
                diffs.append(f"{sub}: {expected[key]!r} != <missing>")
            else:
                diffs += diff_snapshot(expected[key], actual[key], path=sub)
    elif isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            diffs.append(f"{path}: length {len(expected)} != {len(actual)}")
        for i, (e, a) in enumerate(zip(expected, actual)):
            diffs += diff_snapshot(e, a, path=f"{path}[{i}]")
    elif expected != actual:
        diffs.append(f"{path or '<root>'}: {expected!r} != {actual!r}")
    return diffs


def check_ground_truth(ground_truth: Mapping[str, Any],
                       snapshot: Mapping[str, Any]) -> list[str]:
    """Cross-check a snapshot against the manifest's independently-declared ground truth.

    The golden file is *derived* (it can drift with the code); the manifest's `ground_truth` is
    a human-asserted fact about the real demo (final score, round count, roster), so a snapshot
    that disagrees with it is a real regression regardless of whether the golden was updated.
    Returns a list of mismatch messages (empty ⇒ consistent). Only the keys present in
    `ground_truth` are checked, so a partial truth is fine.
    """
    issues: list[str] = []

    if ground_truth.get("rejected"):
        if snapshot.get("outcome") != "rejected":
            issues.append(f"expected a rejection but snapshot outcome is {snapshot.get('outcome')!r}")
        return issues

    if "round_count" in ground_truth and ground_truth["round_count"] != snapshot.get("round_count"):
        issues.append(f"round_count {snapshot.get('round_count')} != truth {ground_truth['round_count']}")

    if "final_score" in ground_truth:
        # Compare as an unordered {CT,T} pair so a side-labeling convention doesn't matter, plus
        # the exact labeled pair — overtime side-switches are exactly what this must catch.
        want, got = ground_truth["final_score"], snapshot.get("final_score") or {}
        if {want.get("CT"), want.get("T")} != {got.get("CT"), got.get("T")}:
            issues.append(f"final_score {got} != truth {want}")

    if "roster" in ground_truth:
        want_ids = {str(s) for s in ground_truth["roster"]}
        got_ids = {p["steamid"] for p in snapshot.get("players", [])}
        if want_ids != got_ids:
            missing = want_ids - got_ids
            extra = got_ids - want_ids
            issues.append(f"roster mismatch (missing={sorted(missing)} extra={sorted(extra)})")

    return issues
