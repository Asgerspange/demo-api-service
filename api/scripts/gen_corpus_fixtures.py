#!/usr/bin/env python
"""Generate the Stage 15 corpus *recorded fixtures* (and their goldens) from compact specs.

The corpus demos are large and live in cold storage, so for the fast CI gate we commit small,
sanitized, internally-consistent stand-in fixtures that mirror what a real ingest emits
(`build_parse_report` + per-round `light_meta` + `sample_positions`). This script is the single
source for those stand-ins: edit a spec here, re-run, and the recorded/*.json + golden/v1/*.json
are rewritten deterministically. When a *real* corpus demo is parsed, capture its outputs with
scripts/add_corpus_reproducer.py instead (that path records the genuine numbers).

    uv run python scripts/add_corpus_reproducer.py   # or:
    uv run python scripts/gen_corpus_fixtures.py && uv run python scripts/regen_corpus_goldens.py

Run from the `api/` directory. Idempotent: same specs → byte-identical files.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ingest.rounds import reason_label  # noqa: E402

RECORDED_DIR = ROOT / "tests" / "corpus" / "recorded"


def _roster(n: int) -> list[dict]:
    return [{"steamid": f"765611900000000{i:02d}", "name": f"player{i:02d}"}
            for i in range(1, n + 1)]


def _running_scores(round_count: int, ct_final: int, t_final: int) -> list[dict]:
    """A monotonic, internally-consistent per-round scoreline ending exactly at (ct_final, t_final).

    Distributes CT/T wins across the rounds deterministically (interleaved) and accumulates the
    running side scores — exactly the shape `_build_single_round` stores in `light_meta`. The
    side-switch *labeling* isn't modeled (light_meta only carries the numbers); real OT side
    correctness is the `slow` real-demo gate.
    """
    assert ct_final + t_final == round_count, "scoreline must sum to round_count"
    # Build the winner sequence: interleave CT and T wins proportionally so it's plausible.
    winners: list[str] = []
    ct_left, t_left = ct_final, t_final
    while ct_left or t_left:
        if ct_left and (t_left == 0 or ct_left * t_final >= t_left * ct_final):
            winners.append("ct"); ct_left -= 1
        else:
            winners.append("t"); t_left -= 1

    rounds: list[dict] = []
    ct = t = 0
    ct_reasons = ["ct_killed", "bomb_defused", "time_ran_out"]
    t_reasons = ["t_killed", "target_bombed", "bomb_exploded"]
    for i, w in enumerate(winners, start=1):
        if w == "ct":
            ct += 1; reason = ct_reasons[i % len(ct_reasons)]
        else:
            t += 1; reason = t_reasons[i % len(t_reasons)]
        rounds.append({
            "round_index": i,
            "winner": w,
            "reason": reason,
            "reason_label": reason_label(reason),
            "CT_score": ct,
            "T_score": t,
            "n_ticks": 2000 + (i * 37) % 800,
        })
    return rounds


def _sampled_positions(seed: int, n: int = 16) -> list[list[int]]:
    """A deterministic spread of integer world positions (a stable coordinate fingerprint)."""
    x = (seed * 2654435761) & 0xFFFFFFFF
    out = []
    for _ in range(n):
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        wx = (x % 4000) - 2000
        x = (1103515245 * x + 12345) & 0x7FFFFFFF
        wy = (x % 4000) - 2000
        out.append([wx, wy])
    return out


def _parsed(*, map_name: str, demo_type: str, is_gotv: bool, tickrate: int | None,
            round_count: int, ct_final: int, t_final: int, roster_n: int = 10,
            anomalies: list[str] | None = None, seed: int) -> dict:
    rounds = _running_scores(round_count, ct_final, t_final)
    roster = _roster(roster_n)
    report = {
        "demo_type": demo_type,
        "is_gotv": is_gotv,
        "tickrate": tickrate,
        "map": map_name,
        "demo_version": "cs2",
        "rounds_found": round_count,
        "rounds_expected": round_count,
        "player_count": len(roster),
        "players": roster,
        "anomalies": anomalies or [],
    }
    return {"parse_report": report, "round_metas": rounds,
            "sampled_positions": _sampled_positions(seed)}


def _rejected(stage: str, error: str) -> dict:
    return {"rejected": True, "stage": stage, "error": error}


# --- the specs (one per `recorded: true` manifest entry) -------------------------------

SPECS: dict[str, dict] = {
    "mm-gotv-inferno-64t": _parsed(
        map_name="de_inferno", demo_type="gotv", is_gotv=True, tickrate=64,
        round_count=6, ct_final=2, t_final=4, seed=101),
    "faceit-128t-mirage": _parsed(
        map_name="de_mirage", demo_type="faceit", is_gotv=True, tickrate=128,
        round_count=8, ct_final=5, t_final=3, seed=128),
    "overtime-nuke": _parsed(
        map_name="de_nuke", demo_type="gotv", is_gotv=True, tickrate=64,
        round_count=35, ct_final=19, t_final=16, seed=64),
    "disconnect-ancient": _parsed(
        map_name="de_ancient", demo_type="gotv", is_gotv=True, tickrate=64,
        round_count=6, ct_final=4, t_final=2, seed=42,
        anomalies=["round 3: 9 players (expected 10 — disconnect/sub?)"]),
    "community-unknown-map": _parsed(
        map_name="de_rats1337", demo_type="gotv", is_gotv=True, tickrate=64,
        round_count=4, ct_final=1, t_final=3, seed=7),
    "pov-rejected": _rejected(
        "classify", "POV (client-recorded) demos are not supported; record a GOTV demo instead"),
    "truncated-corrupt": _rejected(
        "parse", "DemoParseError: unexpected EOF in demo stream (truncated/corrupt)"),
    "csgo-source1-rejected": _rejected(
        "extract", "CSGO (Source 1) demo rejected: this service is CS2-only"),
}


def main() -> None:
    RECORDED_DIR.mkdir(parents=True, exist_ok=True)
    for slug, data in SPECS.items():
        path = RECORDED_DIR / f"{slug}.json"
        path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")
    print(f"\n{len(SPECS)} recorded fixtures written. "
          f"Now run: uv run python scripts/regen_corpus_goldens.py")


if __name__ == "__main__":
    main()
