"""Turn a parsed awpy demo into per-round payload records (Stage 5.2 step 8).

Ported from `demoparser/demo_processor.py` (`_process_demo_data` → `_process_rounds` →
`_process_single_round` and the event sub-processors), with the database/stats/heatmap/
post-processing stripped out: the new pipeline emits the Stage-02 per-round payload
(`{ticks, meta, smokes, infernos, kills}`) to object storage instead of gzipped blobs in MySQL.

`frames_from_demo` does the polars→pandas conversion + grenade-type normalization (needs awpy
data); `build_round_records` is pure pandas and is unit-tested against synthetic frames.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .helpers import (
    create_filtered_kill_tick_dict,
    create_kill_tick_dict,
    create_tick_dict,
    parse_bomb_events,
)


@dataclass
class Frames:
    """Pandas frames the round builder consumes (one per awpy dataframe we use)."""
    ticks: pd.DataFrame
    rounds: pd.DataFrame
    kills: pd.DataFrame
    shots: pd.DataFrame
    grenades: pd.DataFrame
    smokes: pd.DataFrame
    infernos: pd.DataFrame
    bomb_pickup: pd.DataFrame
    bomb_dropped: pd.DataFrame
    bomb_planted: pd.DataFrame


@dataclass
class RoundRecord:
    """One round's viewer payload plus the lightweight meta stored on the DB row / index."""
    round_index: int
    record: dict[str, Any]
    light_meta: dict[str, Any] = field(default_factory=dict)


# CS2 round-end reasons → viewer labels. Strings (awpy 2.x) and the legacy int enum are both
# handled; an unknown reason degrades to a generic label rather than crashing (Stage 11 §11.1.4).
_REASON_LABELS = {
    "t_killed": "Terrorists eliminated", "ct_killed": "Counter-Terrorists eliminated",
    "terrorists_win": "Terrorists win", "cts_win": "Counter-Terrorists win",
    "bomb_defused": "Bomb defused", "target_bombed": "Target bombed",
    "target_saved": "Target saved (time)", "time_ran_out": "Time ran out",
    "bomb_exploded": "Bomb exploded",
    # legacy int enum (the int32 fixture) — best-effort
    1: "Target bombed", 7: "Bomb defused", 8: "Counter-Terrorists win",
    9: "Terrorists win", 12: "Target saved (time)",
}


def reason_label(reason: Any) -> str:
    """Map a round-end reason (str enum or int) to a viewer label; unknown → a generic label."""
    if reason in _REASON_LABELS:
        return _REASON_LABELS[reason]
    if isinstance(reason, str) and reason:
        return reason.replace("_", " ").strip().capitalize()   # readable fallback
    return "Round over"


# --- awpy → pandas ---------------------------------------------------------------------

def _to_pandas(pl_df, *, replace_nan: bool = True) -> pd.DataFrame:
    """polars → pandas, preserving 64-bit ids as exact strings.

    Mirrors `demoparser/helpers.polars_to_pandas_safe`: 64-bit integer columns (steamids)
    are stringified in polars first so they never round-trip through float and lose precision.

    `replace_nan` turns NaN into None so JSON emits `null` — but that `DataFrame.replace`
    scan is O(rows × cols) and ruinously slow on the multi-million-row *ticks* frame, where
    `create_tick_dict` fills NaNs per-column anyway. So callers pass `replace_nan=False` for
    ticks and keep it on for the small event frames that are dumped verbatim.
    """
    import polars as pl

    df = pl_df.clone()
    for col in df.columns:
        if str(df.schema[col]) in ("UInt64", "u64", "Int64", "i64"):
            df = df.with_columns(pl.col(col).cast(pl.Utf8))
    pdf = df.to_pandas()
    return pdf.replace({float("nan"): None}) if replace_nan else pdf


def _normalize_grenades(grenades_pl):
    """Lowercase + canonicalize grenade type names; drop rows with no position."""
    import polars as pl

    return (
        grenades_pl.lazy()
        .drop_nulls(subset=["X", "Y", "Z"])
        .with_columns(pl.col("grenade_type").str.to_lowercase().alias("grenade_type"))
        .with_columns(
            pl.when(pl.col("grenade_type").str.contains("molotov")).then(pl.lit("molotov"))
            .when(pl.col("grenade_type").str.contains("hegrenade")).then(pl.lit("he_grenade"))
            .when(pl.col("grenade_type").str.contains("smoke")).then(pl.lit("smoke"))
            .when(pl.col("grenade_type").str.contains("flashbang")).then(pl.lit("flashbang"))
            .when(pl.col("grenade_type").str.contains("decoy")).then(pl.lit("decoy_grenade"))
            .otherwise(pl.col("grenade_type"))
            .alias("grenade_type")
        )
        .collect()
    )


def frames_from_demo(dem) -> Frames:
    """Extract and convert the awpy dataframes the round builder needs."""
    grenades = _to_pandas(_normalize_grenades(dem.grenades))
    kills = _to_pandas(dem.kills)
    if "attacker_steamid" in kills.columns:
        kills["attacker_steamid"] = kills["attacker_steamid"].astype(str)
    return Frames(
        ticks=_to_pandas(dem.ticks, replace_nan=False),  # filled per-column in create_tick_dict
        rounds=_to_pandas(dem.rounds),
        kills=kills,
        shots=_to_pandas(dem.shots),
        grenades=grenades,
        smokes=_to_pandas(dem.smokes),
        infernos=_to_pandas(dem.infernos),
        bomb_pickup=_to_pandas(dem.events["bomb_pickup"]),
        bomb_dropped=_to_pandas(dem.events["bomb_dropped"]),
        bomb_planted=_to_pandas(dem.events["bomb_planted"]),
    )


# --- event sub-processors (mutate tick_dict) -------------------------------------------

_EMPTY = pd.DataFrame()


def _process_weapon_fires(r_shots: pd.DataFrame, tick_dict: dict) -> None:
    if r_shots is None or r_shots.empty:
        return
    cols = [c for c in ("tick", "player_name", "player_steamid", "weapon", "player_yaw",
                        "player_X", "player_Y", "round_num") if c in r_shots.columns]
    for wf in r_shots[cols].to_dict(orient="records"):
        name = str(wf["weapon"]).lower()
        if not any(t in name for t in
                   ("grenade", "knife", "c4", "bayonet", "flash", "molotov", "smoke", "decoy")):
            tick_dict[int(wf["tick"])]["weapon_fires"].append(wf)


def _process_bomb_events(r_pickup, r_dropped, r_planted, last_tick: int, tick_dict: dict) -> None:
    bomb_ticks = parse_bomb_events(
        r_pickup if r_pickup is not None else _EMPTY,
        r_dropped if r_dropped is not None else _EMPTY,
        r_planted if r_planted is not None else _EMPTY,
        last_tick,
    )
    for tick, bomb in bomb_ticks.items():
        tick_dict[int(tick)]["bomb"] = bomb


def _process_grenades(r_grenades: pd.DataFrame, tick_dict: dict) -> None:
    if r_grenades is None or r_grenades.empty:
        return
    cols = [c for c in ("thrower_steamid", "thrower", "grenade_type", "tick",
                        "X", "Y", "Z", "entity_id", "round_num") if c in r_grenades.columns]
    for g in r_grenades[cols].to_dict(orient="records"):
        g["thrower_steamid"] = str(g["thrower_steamid"])
        tick_dict[int(g["tick"])]["grenades"].append(g)


_SMOKE_COLS = ("entity_id", "start_tick", "end_tick", "thrower_name", "thrower_side",
               "thrower_steamid", "X", "Y", "Z", "round_num")


def _process_smokes_infernos(r_smokes, r_infernos) -> tuple[list, list]:
    def _select(df):
        if df is None or df.empty:
            return []
        return df[[c for c in _SMOKE_COLS if c in df.columns]].to_dict(orient="records")
    return _select(r_smokes), _select(r_infernos)


def _as_list(arr) -> list:
    return [float(v) if not (math.isnan(v) or math.isinf(v)) else None for v in arr]


def _create_utilities(r_grenades, r_smokes, r_infernos, r_players) -> dict:
    """Per-utility origin/bounce/landing summary (ported from `_create_utilities`).

    Not part of the validated payload schema, so it rides along under `meta['utility']`.
    """
    utilities: dict[str, dict] = {}
    if r_grenades is None or r_grenades.empty:
        return utilities

    for entity_id, gdata in r_grenades.groupby("entity_id"):
        thrower = gdata["thrower"].iloc[0]
        steamid = gdata["thrower_steamid"].iloc[0]
        gtype = gdata["grenade_type"].iloc[0]
        coords = gdata[["X", "Y", "Z"]].to_numpy(dtype=float)

        origin = _as_list(coords[0])
        last_pos = _as_list(coords[-1])
        velocities = np.diff(coords, axis=0)

        bounces = []
        for i in range(1, len(velocities)):
            v1, v2 = velocities[i - 1], velocities[i]
            n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
            if n1 == 0 or n2 == 0:
                continue
            dot = np.clip(np.dot(v1 / n1, v2 / n2), -1.0, 1.0)
            if np.degrees(np.arccos(dot)) > 30 or n2 < n1 * 0.5:
                bounces.append(_as_list(coords[i]))

        if gtype in ("smoke", "smokegrenade") and r_smokes is not None and not r_smokes.empty:
            sm = r_smokes[r_smokes["entity_id"] == entity_id]
            landing = _as_list([sm["X"].iloc[0], sm["Y"].iloc[0], sm["Z"].iloc[0]]) if not sm.empty else last_pos
        elif gtype in ("molotov", "incendiary") and r_infernos is not None and not r_infernos.empty:
            inf = r_infernos[r_infernos["entity_id"] == entity_id]
            landing = _as_list([inf["X"].iloc[0], inf["Y"].iloc[0], inf["Z"].iloc[0]]) if not inf.empty else last_pos
        else:
            landing = last_pos

        thrower_side = None
        if r_players is not None and not r_players.empty:
            row = r_players[r_players["name"] == thrower]
            if not row.empty:
                thrower_side = row["side"].iloc[0]

        utilities[str(entity_id)] = {
            "thrower": str(thrower) if thrower is not None else None,
            "steamid": str(steamid) if steamid is not None else None,
            "type": str(gtype) if gtype is not None else None,
            "origin": origin,
            "bounces": bounces,
            "end": landing,
            "thrower_side": str(thrower_side) if thrower_side is not None else None,
        }
    return utilities


# --- per-round + orchestration ---------------------------------------------------------

def _assign_round_num(df: pd.DataFrame, spans: list[tuple[int, int, int]]) -> pd.DataFrame:
    """Tag each event row with its round_num from (round_num, start, end) tick spans."""
    if df is None or df.empty or "tick" not in df.columns:
        return df
    df = df.copy()
    df["round_num"] = None
    for rn, start, end in spans:
        df.loc[(df["tick"] >= start) & (df["tick"] <= end), "round_num"] = rn
    return df


def _groups(df: pd.DataFrame) -> dict:
    if df is None or df.empty or "round_num" not in df.columns:
        return {}
    return {rn: g for rn, g in df.groupby("round_num")}


def _build_single_round(round_number: int, round_data: pd.DataFrame, rounds_by_num: dict,
                        scores: tuple[int, int], rg: dict) -> tuple[RoundRecord, tuple[int, int]]:
    """Build one round's record; return it plus the updated (team_a, team_b) score tuple."""
    team_a_score, team_b_score = scores
    tick_dict = create_tick_dict(round_data)

    # numpy array cells (awpy list-columns) → plain lists so the payload encodes cleanly.
    round_info = {k: (v.tolist() if isinstance(v, np.ndarray) else v)
                  for k, v in dict(rounds_by_num[round_number]).items()}

    target_tick = int(round_info["official_end"]) - 10
    if target_tick in tick_dict:
        end_players = tick_dict[target_tick]["players"]
    else:
        nearest = min(tick_dict.keys(), key=lambda t: abs(t - target_tick))
        end_players = tick_dict[nearest]["players"]

    round_info["t_balance"] = sum(
        p["balance"] for p in end_players
        if p.get("team_name", "") and str(p["team_name"]).lower() == "t")
    round_info["ct_balance"] = sum(
        p["balance"] for p in end_players
        if p.get("team_name", "") and str(p["team_name"]).lower() == "ct")

    winning_side = str(round_info["winner"]).lower()
    round_info["winners"] = [p.get("steamid") for p in end_players if p["team_name"] == winning_side]
    round_info["losers"] = [p.get("steamid") for p in end_players if p["team_name"] != winning_side]

    first_side = round_data.iloc[0]["side"]
    current_team = first_side if isinstance(first_side, str) and first_side else "CT"
    won = current_team[0].upper() == str(round_info["winner"])[0].upper()
    new_a = team_a_score + (1 if won else 0)
    new_b = team_b_score + (0 if won else 1)
    round_info["CT_score"] = new_a if str(current_team).upper() == "CT" else new_b
    round_info["T_score"] = new_b if str(current_team).upper() == "CT" else new_a
    round_info["header"] = rounds_by_num[round_number].get("header", {})

    r_kills = rg["kills"].get(round_number, _EMPTY)
    _rk = r_kills if r_kills is not None else _EMPTY

    def _kills_by(sid):
        if _rk is None or _rk.empty:
            return 0
        return int((_rk["attacker_steamid"] == sid).sum())

    round_info["alive_players"] = {
        p["steamid"]: {"name": p["name"], "team_name": p["team_name"], "kills": _kills_by(p["steamid"])}
        for p in end_players if (p["health"] or 0) > 0}
    round_info["dead_players"] = {
        p["steamid"]: {"name": p["name"], "team_name": p["team_name"], "kills": _kills_by(p["steamid"])}
        for p in end_players if (p["health"] or 0) <= 0}
    round_info["kills"] = create_filtered_kill_tick_dict(_rk) if not _rk.empty else {}

    _process_weapon_fires(rg["shots"].get(round_number, _EMPTY), tick_dict)
    _process_bomb_events(
        rg["pickup"].get(round_number, _EMPTY),
        rg["dropped"].get(round_number, _EMPTY),
        rg["planted"].get(round_number, _EMPTY),
        int(round_data["tick"].max()), tick_dict)
    r_grenades = rg["grenades"].get(round_number, _EMPTY)
    _process_grenades(r_grenades, tick_dict)
    smokes, infernos = _process_smokes_infernos(
        rg["smokes"].get(round_number, _EMPTY), rg["infernos"].get(round_number, _EMPTY))
    round_info["utility"] = _create_utilities(
        r_grenades, rg["smokes"].get(round_number, _EMPTY),
        rg["infernos"].get(round_number, _EMPTY), rg["players"].get(round_number, _EMPTY))

    record = {
        "ticks": dict(tick_dict),
        "meta": round_info,
        "smokes": smokes,
        "infernos": infernos,
        "kills": create_kill_tick_dict(_rk) if not _rk.empty else {},
    }
    round_info["reason_label"] = reason_label(round_info.get("reason"))
    light_meta = {
        "round_index": int(round_number),
        "winner": round_info.get("winner"),
        "reason": round_info.get("reason"),
        "reason_label": round_info["reason_label"],
        "T_score": round_info.get("T_score"),
        "CT_score": round_info.get("CT_score"),
        "start": _int_or_none(round_info.get("start")),
        "end": _int_or_none(round_info.get("end")),
        "n_ticks": len(tick_dict),
    }
    return RoundRecord(int(round_number), record, light_meta), (new_a, new_b)


def _int_or_none(v) -> int | None:
    return None if v is None else int(v)


def build_round_records(frames: Frames) -> list[RoundRecord]:
    """Build every round's payload record (in round order), tracking the running scoreline."""
    rounds_by_num = {r["round_num"]: r for r in frames.rounds.to_dict(orient="records")}
    spans = [(r["round_num"], int(r["start"]), int(r["end"]))
             for r in frames.rounds.to_dict(orient="records")]

    rg = {
        "shots": _groups(frames.shots),
        "kills": _groups(frames.kills),
        "grenades": _groups(frames.grenades),
        "smokes": _groups(frames.smokes),
        "infernos": _groups(frames.infernos),
        "pickup": _groups(_assign_round_num(frames.bomb_pickup, spans)),
        "dropped": _groups(_assign_round_num(frames.bomb_dropped, spans)),
        "planted": _groups(_assign_round_num(frames.bomb_planted, spans)),
        "players": {
            rn: g[[c for c in ("steamid", "name", "side", "team_clan_name") if c in g.columns]]
                  .drop_duplicates("steamid")
            for rn, g in frames.ticks.groupby("round_num")},
    }

    records: list[RoundRecord] = []
    scores = (0, 0)
    for round_number, round_data in frames.ticks.groupby("round_num"):
        if round_number not in rounds_by_num:
            continue
        rec, scores = _build_single_round(round_number, round_data, rounds_by_num, scores, rg)
        records.append(rec)
    return records


def _kill_counts(kills_df) -> dict[str, list[int]]:
    """Aggregate K / D / A / HS per steamid straight from the killfeed (Stage 11 §11.2).

    The killfeed is the source of truth for frags — exact and always present, unlike the
    cumulative `*_total` tick fields (which some demos don't carry and which need a live
    demo to trust). Returns {steamid: [kills, deaths, assists, headshots]}.
    """
    counts: dict[str, list[int]] = {}
    if kills_df is None or getattr(kills_df, "empty", True):
        return counts

    def _series(col):
        return kills_df[col].astype(str) if col in kills_df.columns else None

    def _tally(series, idx, mask=None):
        if series is None:
            return
        vals = series[mask] if mask is not None else series
        for sid, n in vals.value_counts().items():
            sid = str(sid)
            if sid in ("", "0", "None", "nan"):
                continue
            counts.setdefault(sid, [0, 0, 0, 0])[idx] += int(n)

    attacker = _series("attacker_steamid")
    # A frag is an attacker who isn't the victim (drop suicides / world deaths).
    victim = _series("victim_steamid")
    real = (attacker != victim) if (attacker is not None and victim is not None) else None
    _tally(attacker, 0, real)
    _tally(victim, 1)
    _tally(_series("assister_steamid"), 2)
    if "headshot" in kills_df.columns and attacker is not None:
        hs_mask = kills_df["headshot"].fillna(False).astype(bool)
        if real is not None:
            hs_mask = hs_mask & real
        _tally(attacker, 3, hs_mask)
    return counts


def build_scoreboard(frames: Frames, rounds: int) -> list[dict[str, Any]]:
    """Per-player end-of-match scoreboard (Stage 11 §11.2).

    K/D/A/HS come from the killfeed (`_kill_counts` — exact, always present). Team, name and
    per-round damage come from the tick stream: `side` is the player's final side, `damage_total`
    (cumulative in CS2 GOTV) gives ADR = damage/rounds. HS% = headshots/kills; rating is the same
    lightweight ~1.0 approximation the FACEIT path uses. Sorted by kills, best first.
    """
    df = getattr(frames, "ticks", None)
    if df is None or df.empty or "steamid" not in df.columns:
        return []

    rounds = max(1, int(rounds or 0))
    team_col = "team_name" if "team_name" in df.columns else ("side" if "side" in df.columns else None)
    frags = _kill_counts(getattr(frames, "kills", None))

    board: list[dict[str, Any]] = []
    for sid, g in df.groupby("steamid"):
        sid = str(sid)
        if sid in ("", "0", "None", "nan"):
            continue
        team = ""
        if team_col is not None:
            teams = [str(t).lower() for t in g[team_col].dropna().tolist()
                     if str(t).lower() in ("t", "ct")]
            team = teams[-1] if teams else ""
        if team not in ("t", "ct"):   # skip coaches/casters/spectators
            continue
        names = [n for n in g["name"].dropna().tolist() if n] if "name" in g.columns else []
        kills, deaths, assists, hs = frags.get(sid, [0, 0, 0, 0])
        damage = int(g["damage_total"].max()) if "damage_total" in g.columns and not g["damage_total"].isna().all() else 0
        adr = round(damage / rounds, 1)
        kd = kills / deaths if deaths else float(kills)
        board.append({
            "steamid": sid,
            "name": names[-1] if names else "",
            "team": team,
            "kills": kills, "deaths": deaths, "assists": assists,
            "adr": adr,
            "hs": round(hs / kills * 100) if kills else 0,
            "rating": round((kd * 0.5) + ((adr / 100) * 0.5), 2),
        })
    board.sort(key=lambda p: p["kills"], reverse=True)
    return board


def build_parse_report(cls, frames: Frames, records: list[RoundRecord]) -> dict[str, Any]:
    """A structured parse report for `demos.meta` (Stage 11 §11.2) — detected type, tickrate,
    rounds, players, and anomalies (rounds without a full 5v5, indicating disconnects/subs).

    Invaluable for debugging real-world demos and the Stage 15 corpus.
    """
    # distinct real participants across the match
    players: dict[str, str] = {}
    for rec in records:
        for tick in rec.record["ticks"].values():
            for p in tick["players"]:
                players.setdefault(str(p["steamid"]), p.get("name") or "")

    anomalies: list[str] = []
    for rec in records:
        # peek the first tick's roster size for this round
        first = next(iter(rec.record["ticks"].values()), {"players": []})
        n = len(first["players"])
        if n and n != 10:
            anomalies.append(f"round {rec.round_index}: {n} players (expected 10 — disconnect/sub?)")

    rounds_found = len(records)
    rounds_frame = getattr(frames, "rounds", None)
    expected = len(rounds_frame) if rounds_frame is not None else None
    if expected is not None and rounds_found != expected:
        anomalies.append(f"{rounds_found} rounds built vs {expected} in the rounds frame")

    return {
        "demo_type": getattr(cls, "demo_type", None),
        "is_gotv": getattr(cls, "is_gotv", None),
        "tickrate": getattr(cls, "tickrate", None),
        "map": getattr(cls, "map_name", None),
        "demo_version": getattr(cls, "demo_version", None),
        "rounds_found": rounds_found,
        "rounds_expected": expected,
        "player_count": len(players),
        "players": [{"steamid": s, "name": n} for s, n in players.items()],
        "anomalies": anomalies,
    }
