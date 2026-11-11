"""Per-round dataframe → payload-record helpers.

Ported from the proven `demoparser/helpers.py` (the reader contract is unchanged), with two
deliberate changes for the new pipeline:
- `create_tick_dict` now keeps the **full v1 player field set** the viewer reads
  (`app/payload.py:PLAYER_FIELDS`) — the old version omitted `flash_duration`/`has_defuser`/
  `has_helmet`/`is_walking`, which `RoundLoader.worker.js` actually consumes.
- tick keys are coerced to plain `int` so the `orjson` `OPT_NON_STR_KEYS` encode is clean.

Only the structures that feed the per-round payload are ported here; the stats/heatmap/
post-processing helpers are out of scope for Stage 05.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd


def _native(value: Any) -> Any:
    """Convert a numpy array cell to a plain list (object-dtype arrays break orjson).

    Numpy *scalars* are left untouched — orjson serializes those natively and fast; only
    arrays (e.g. an awpy list-column cell like `inventory`) must be flattened.
    """
    return value.tolist() if isinstance(value, np.ndarray) else value


def _native_record(record: dict) -> dict:
    return {k: _native(v) for k, v in record.items()}

# Columns we pull out of the awpy ticks frame for each player snapshot. Superset of
# PLAYER_FIELDS (minus the side→team_name rename) plus a few the meta computation needs.
_TICK_FIELDS = frozenset({
    "tick", "X", "Y", "Z", "yaw", "pitch",
    "active_weapon_name", "armor_value", "armor", "balance", "health",
    "flash_duration", "has_defuser", "has_helmet", "is_walking",
    "inventory", "name", "steamid", "team_clan_name", "side",
    "kills_total", "deaths_total", "assists_total",
})

_STR_COLS = ("active_weapon_name", "name", "steamid", "team_clan_name", "team_name")
_BOOL_COLS = ("has_defuser", "has_helmet", "is_walking")
_NUM_COLS = ("balance", "health", "armor_value", "yaw", "pitch", "flash_duration",
             "kills_total", "deaths_total", "assists_total")


def create_tick_dict(round_data: pd.DataFrame) -> defaultdict:
    """Group a round's player frames into `{tick: {players, weapon_fires, bomb, grenades}}`.

    Produces the player records the viewer reads: coordinates rounded to 0.1, `side` renamed
    to `team_name`, `armor`/`armor_value` coalesced, NaNs filled, `inventory` normalized to a
    list. The sparse structures start empty and are filled by the event processors.
    """
    keep = [c for c in round_data.columns if c in _TICK_FIELDS]
    df = round_data[keep].copy()

    # Coalesce armor/armor_value → armor_value (column name varies across awpy versions).
    if "armor" in df.columns:
        if "armor_value" in df.columns:
            df["armor_value"] = df["armor_value"].where(
                df["armor_value"].notna() & (df["armor_value"] != 0), df["armor"]
            )
            df.drop(columns=["armor"], inplace=True)
        else:
            df.rename(columns={"armor": "armor_value"}, inplace=True)

    if "side" in df.columns:
        df.rename(columns={"side": "team_name"}, inplace=True)

    for col in ("X", "Y", "Z"):
        if col in df.columns:
            df[col] = df[col].round(1).fillna(0)

    str_cols = [c for c in _STR_COLS if c in df.columns]
    num_cols = [c for c in _NUM_COLS if c in df.columns]
    bool_cols = [c for c in _BOOL_COLS if c in df.columns]
    if str_cols:
        df[str_cols] = df[str_cols].fillna("")
    if num_cols:
        df[num_cols] = df[num_cols].fillna(0)
    if bool_cols:
        df[bool_cols] = df[bool_cols].fillna(False)

    records = df.to_dict(orient="records")
    tick_dict: defaultdict = defaultdict(
        lambda: {"players": [], "weapon_fires": [], "bomb": None, "grenades": []}
    )
    for record in records:
        # Filter non-participants (coaches/casters/spectators) — only real T/CT players belong
        # in the payload (Stage 11 §11.1.6). Normalize the side to lowercase for the viewer.
        team = str(record.get("team_name", "")).lower()
        if team not in ("t", "ct"):
            continue
        record["team_name"] = team
        # inventory is an awpy list-column: a numpy object array (or NaN). The viewer wants a
        # plain list, and an object ndarray would break the orjson encode.
        inv = record.get("inventory")
        if isinstance(inv, np.ndarray):
            record["inventory"] = inv.tolist()
        elif not isinstance(inv, list):
            record["inventory"] = []
        tick_dict[int(record.pop("tick"))]["players"].append(record)
    return tick_dict


def parse_bomb_events(pickups: pd.DataFrame, drops: pd.DataFrame, plants: pd.DataFrame,
                      last_round_tick: int) -> dict:
    """Interpolate the bomb's position per tick across drop→pickup spans and the plant window.

    Ported from `demoparser/helpers.parse_bomb_events`. After a drop the bomb is interpolated
    toward the next pickup (or the round end), then sits at the pickup until the next event;
    after a plant it holds the plant position for up to 40 s, with `planted_ticks` counting up.
    """
    tickdict: dict[int, dict] = {}

    for drop in drops.to_dict(orient="records"):
        closest = pickups.loc[pickups["tick"] > drop["tick"]]
        closest_pickup = closest.iloc[0] if not closest.empty else None
        next_tick = int(closest_pickup["tick"]) if closest_pickup is not None else int(last_round_tick)
        max_ticks = min(next_tick - int(drop["tick"]), 64)
        if closest_pickup is None:
            closest_pickup = drop

        def _coord(row, axis):
            v = row[f"user_{axis}"]
            return float(v) if v is not None and not pd.isna(v) else 0.0

        dx, dy, dz = _coord(drop, "X"), _coord(drop, "Y"), _coord(drop, "Z")
        px, py, pz = _coord(closest_pickup, "X"), _coord(closest_pickup, "Y"), _coord(closest_pickup, "Z")

        for tick in range(int(drop["tick"]), int(drop["tick"]) + max_ticks):
            t = (tick - int(drop["tick"])) / max_ticks if max_ticks else 0.0
            tickdict[tick] = {
                "X": dx + t * (px - dx),
                "Y": dy + t * (py - dy),
                "Z": dz + t * (pz - dz),
                "planted_ticks": None,
            }
        for tick in range(int(drop["tick"]) + max_ticks, next_tick):
            tickdict[tick] = {"X": px, "Y": py, "Z": pz, "planted_ticks": None}

    plant_records = plants.to_dict(orient="records")
    if not plant_records:
        return tickdict

    plant = plant_records[0]
    max_tick = min(int(last_round_tick), 64 * 40 + int(plant["tick"]))
    for tick in range(int(plant["tick"]), max_tick):
        tickdict[tick] = {
            "X": float(plant["user_X"]),
            "Y": float(plant["user_Y"]),
            "Z": float(plant["user_Z"]),
            "planted_ticks": tick - int(plant["tick"]),
        }
    return tickdict


def create_kill_tick_dict(round_data: pd.DataFrame) -> dict:
    """Group every kill column by tick (full kill records — the payload's `kills`)."""
    tick_dict: defaultdict = defaultdict(list)
    for record in round_data.to_dict(orient="records"):
        tick_dict[int(record["tick"])].append(_native_record(record))
    return dict(tick_dict)


_FILTERED_KILL_FIELDS = (
    "tick", "headshot", "thrusmoke", "victim_name", "victim_side",
    "assistedflash", "attacker_side", "attackerblind", "attackerinair",
    "victim_steamid", "assister_steamid", "attacker_steamid",
    "attacker_name", "assister_name", "noscope", "weapon",
)


def create_filtered_kill_tick_dict(round_data: pd.DataFrame) -> dict:
    """Group a trimmed kill record by tick (the killfeed subset stored in round `meta`)."""
    tick_dict: defaultdict = defaultdict(list)
    for record in round_data.to_dict(orient="records"):
        filtered = {f: _native(record.get(f)) for f in _FILTERED_KILL_FIELDS if f in record}
        tick_dict[int(record["tick"])].append(filtered)
    return dict(sorted(tick_dict.items()))
