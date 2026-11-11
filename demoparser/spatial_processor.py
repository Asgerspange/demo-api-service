"""
spatial_processor.py

Computes all spatial heatmap data from demo DataFrames and stores in demo_spatial.
Called from post_processor.py concurrently with position_dominance computation.

Types computed:
  paths   — player movement paths per round (sampled every 4th live tick)
  utility — grenade landing positions (smoke, molotov, flash, HE, decoy)
  shots   — player positions when firing (engagement positions)
  plants  — bomb plant positions
  entries — player positions at freeze_end (start-of-round positioning)
"""

from __future__ import annotations

import asyncio
import base64
import gzip
import json
import math
from collections import defaultdict
from typing import Any

import aiomysql
import pandas as pd
from loguru import logger


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _compress(data: Any) -> str:
    """JSON encode, gzip compress, base64 encode → string for DB storage."""
    raw = json.dumps(data, separators=(',', ':')).encode()
    return base64.b64encode(gzip.compress(raw, compresslevel=3)).decode()


def _safe_float(v, default: float = 0.0) -> float:
    try:
        f = float(v)
        return default if (f != f or abs(f) > 1e9) else f  # NaN / inf check
    except (TypeError, ValueError):
        return default


def _safe_str(v) -> str:
    s = str(v) if v is not None else ""
    return "" if s in ("None", "nan", "NaN") else s


# ─── Movement paths ───────────────────────────────────────────────────────────

def compute_paths(
    frame_df: pd.DataFrame,
    rounds_df: pd.DataFrame,
) -> dict:
    """
    Sample player positions every 4 ticks within live round windows.
    Returns:
    {
        steamid: {
            round_num: [
                { x, y, side }  -- side: 't' or 'ct'
            ]
        }
    }
    """
    if frame_df is None or frame_df.empty:
        return {}

    SAMPLE = 4  # every 4 ticks ≈ 16ms at 64tick

    # Build valid tick windows (freeze_end → official_end) per round
    valid: dict[int, tuple[int, int]] = {}  # round_num → (freeze_end, official_end)
    if rounds_df is not None and not rounds_df.empty:
        for _, r in rounds_df.iterrows():
            try:
                rn_raw = r.get("round_num", r.get("round_number", 0))
                fe_raw = r.get("freeze_end",   r.get("start", 0))
                oe_raw = r.get("official_end", r.get("end",   0))
                # Skip rows with NaN values
                if any(v is None or (isinstance(v, float) and math.isnan(v))
                       for v in [rn_raw, fe_raw, oe_raw]):
                    continue
                rn = int(rn_raw or 0)
                fe = int(fe_raw or 0)
                oe = int(oe_raw or 0)
                if rn > 0 and fe > 0 and oe > fe:
                    valid[rn] = (fe, oe)
            except (TypeError, ValueError):
                continue

    # Build tick → round_num lookup
    tick_to_round: dict[int, int] = {}
    for rn, (fe, oe) in valid.items():
        for t in range(fe, oe + 1, SAMPLE):
            tick_to_round[t] = rn

    result: dict[str, dict[int, list]] = defaultdict(lambda: defaultdict(list))

    needed_cols = {"tick", "steamid", "X", "Y", "health"}
    side_col    = "team_name" if "team_name" in frame_df.columns else "side"
    if side_col in frame_df.columns:
        needed_cols.add(side_col)

    available = [c for c in needed_cols if c in frame_df.columns]
    df = frame_df[available].copy()

    # Sample every Nth tick
    ticks = sorted(df["tick"].unique())
    sampled = set(ticks[i] for i in range(0, len(ticks), SAMPLE))
    df = df[df["tick"].isin(sampled)]

    for row in df.itertuples(index=False):
        try:
            tick = int(_safe_float(getattr(row, "tick", 0)))
        except (TypeError, ValueError):
            continue
        rn   = tick_to_round.get(tick)
        if rn is None:
            continue

        sid    = _safe_str(getattr(row, "steamid", ""))
        health = _safe_float(getattr(row, "health", 0))
        if not sid or health <= 0:
            continue

        x = round(_safe_float(getattr(row, "X", 0)), 1)
        y = round(_safe_float(getattr(row, "Y", 0)), 1)

        raw_side = str(getattr(row, side_col, "") or "").lower()
        side = "t" if raw_side in ("t", "terrorist") else "ct" if raw_side in ("ct", "counterterrorist") else None
        if side is None:
            continue

        result[sid][rn].append({"x": x, "y": y, "s": side[0]})  # 's' = 't' or 'c' (compact)

    return {sid: dict(rounds) for sid, rounds in result.items()}


# ─── Utility landing positions ────────────────────────────────────────────────

def compute_utility(
    smokes_df:   pd.DataFrame,
    infernos_df: pd.DataFrame,
    grenades_df: pd.DataFrame,
) -> dict:
    """
    Grenade landing/detonation positions.
    Returns:
    {
        "smoke":    [{ x, y, steamid, round }],
        "molotov":  [...],
        "flash":    [...],
        "he":       [...],
        "decoy":    [...],
    }
    """
    result: dict[str, list] = {
        "smoke": [], "molotov": [], "flash": [], "he": [], "decoy": []
    }

    # Smokes — use landing position (X, Y at start_tick)
    if smokes_df is not None and not smokes_df.empty:
        for row in smokes_df.itertuples(index=False):
            sid = _safe_str(getattr(row, "thrower_steamid", "") or
                            getattr(row, "steamid", ""))
            rn  = int(getattr(row, "round_num", 0) or 0)
            x   = round(_safe_float(getattr(row, "X", 0)), 1)
            y   = round(_safe_float(getattr(row, "Y", 0)), 1)
            if x or y:
                result["smoke"].append({"x": x, "y": y, "sid": sid, "r": rn})

    # Infernos (molotovs)
    if infernos_df is not None and not infernos_df.empty:
        for row in infernos_df.itertuples(index=False):
            sid = _safe_str(getattr(row, "thrower_steamid", "") or
                            getattr(row, "steamid", ""))
            rn  = int(getattr(row, "round_num", 0) or 0)
            x   = round(_safe_float(getattr(row, "X", 0)), 1)
            y   = round(_safe_float(getattr(row, "Y", 0)), 1)
            if x or y:
                result["molotov"].append({"x": x, "y": y, "sid": sid, "r": rn})

    # Grenades — flash, HE, decoy — use detonation position (last trajectory point or X/Y)
    GRENADE_TYPE_MAP = {
        "flashbang":          "flash",
        "cflashbang":         "flash",
        "he_grenade":         "he",
        "chegrenade":         "he",
        "hegrenade":          "he",
        "decoy_grenade":      "decoy",
        "cdecoygrenade":      "decoy",
        "smoke_grenade":      None,   # handled above via smokes_df
        "csmokegrenade":      None,
        "molotov":            None,   # handled above via infernos_df
        "cmolotovprojectile": None,
        "incendiary_grenade": None,
    }

    if grenades_df is not None and not grenades_df.empty:
        seen: set[tuple] = set()  # deduplicate by (entity_id, round)
        for row in grenades_df.itertuples(index=False):
            raw_type = str(getattr(row, "grenade_type", "") or "").lower().replace(" ", "_")
            gtype    = GRENADE_TYPE_MAP.get(raw_type)
            if gtype is None:
                continue

            eid = getattr(row, "entity_id", None)
            rn  = int(getattr(row, "round_num", 0) or 0)
            key = (eid, rn)
            if key in seen:
                continue
            seen.add(key)

            sid = _safe_str(getattr(row, "thrower_steamid", "") or
                            getattr(row, "steamid", ""))
            x   = round(_safe_float(getattr(row, "X", 0)), 1)
            y   = round(_safe_float(getattr(row, "Y", 0)), 1)
            if x or y:
                result[gtype].append({"x": x, "y": y, "sid": sid, "r": rn})

    return result


# ─── Shot / engagement positions ──────────────────────────────────────────────

def compute_shots(shots_df: pd.DataFrame) -> dict:
    """
    Player positions when they fire a weapon (excluding utility throws).
    Returns:
    {
        steamid: [{ x, y, weapon, round }]
    }
    """
    if shots_df is None or shots_df.empty:
        return {}

    SKIP_WEAPONS = {
        "flashbang", "hegrenade", "smokegrenade", "molotov",
        "incgrenade", "decoy", "c4", "knife", "bayonet",
    }

    result: dict[str, list] = defaultdict(list)
    seen: set[tuple] = set()

    for row in shots_df.itertuples(index=False):
        try:
            weapon = str(getattr(row, "weapon", "") or "").lower().replace(" ", "_")
            if any(skip in weapon for skip in SKIP_WEAPONS):
                continue

            sid  = _safe_str(getattr(row, "player_steamid", "") or
                             getattr(row, "steamid", ""))
            rn   = int(_safe_float(getattr(row, "round_num", 0)))
            tick = int(_safe_float(getattr(row, "tick", 0)))

            # Deduplicate — max one point per player per second (64 ticks)
            key = (sid, rn, tick // 64)
            if key in seen:
                continue
            seen.add(key)

            x = round(_safe_float(getattr(row, "player_X", 0) or
                                   getattr(row, "X", 0)), 1)
            y = round(_safe_float(getattr(row, "player_Y", 0) or
                                   getattr(row, "Y", 0)), 1)
            if sid and (x or y):
                result[sid].append({"x": x, "y": y, "w": weapon[:16], "r": rn})
        except (TypeError, ValueError):
            continue

    return dict(result)


# ─── Bomb plant positions ─────────────────────────────────────────────────────

def compute_plants(
    planted_df: pd.DataFrame,
    frame_df:   pd.DataFrame,
) -> list:
    """
    Returns [{ x, y, round, steamid }] for each bomb plant event.
    Uses frame_df to find planter's position at plant tick.
    """
    if planted_df is None or planted_df.empty:
        return []

    result = []

    for row in planted_df.itertuples(index=False):
        try:
            tick = int(_safe_float(getattr(row, "tick", 0)))
            rn   = int(_safe_float(getattr(row, "round_num", 0)))
            sid  = _safe_str(getattr(row, "player_steamid", "") or
                              getattr(row, "steamid", ""))

            if not tick:
                continue

            # Find planter position at plant tick from frame_df
            if frame_df is not None and not frame_df.empty and sid:
                nearby = frame_df[
                    (frame_df["tick"] >= tick - 32) &
                    (frame_df["tick"] <= tick + 32)
                ]
                sid_col = "steamid"
                if sid_col in nearby.columns:
                    player_rows = nearby[nearby[sid_col].astype(str) == sid]
                    if not player_rows.empty:
                        px = round(_safe_float(player_rows.iloc[0].get("X", 0)), 1)
                        py = round(_safe_float(player_rows.iloc[0].get("Y", 0)), 1)
                        result.append({"x": px, "y": py, "r": rn, "sid": sid})
                        continue

            # Fallback: use event X/Y if available
            x = round(_safe_float(getattr(row, "X", 0) or getattr(row, "x", 0)), 1)
            y = round(_safe_float(getattr(row, "Y", 0) or getattr(row, "y", 0)), 1)
            if x or y:
                result.append({"x": x, "y": y, "r": rn, "sid": sid})
        except (TypeError, ValueError):
            continue

    return result


# ─── Entry positions ──────────────────────────────────────────────────────────

def compute_entries(
    frame_df:  pd.DataFrame,
    rounds_df: pd.DataFrame,
) -> dict:
    """
    First alive position per player per round after freeze_end.
    Shows initial aggressive positioning / default setups.
    Returns:
    {
        steamid: [{ x, y, side, round }]
    }
    """
    if frame_df is None or frame_df.empty:
        return {}

    # freeze_end per round
    freeze_ends: dict[int, int] = {}
    if rounds_df is not None and not rounds_df.empty:
        for _, r in rounds_df.iterrows():
            try:
                rn_raw = r.get("round_num", r.get("round_number", 0))
                fe_raw = r.get("freeze_end", r.get("start", 0))
                if any(v is None or (isinstance(v, float) and math.isnan(v))
                       for v in [rn_raw, fe_raw]):
                    continue
                rn = int(rn_raw or 0)
                fe = int(fe_raw or 0)
                if rn > 0 and fe > 0:
                    freeze_ends[rn] = fe
            except (TypeError, ValueError):
                continue

    # Build round_num column from tick if not present
    if "round_num" not in frame_df.columns:
        return {}

    result: dict[str, list] = defaultdict(list)
    side_col = "team_name" if "team_name" in frame_df.columns else "side"

    for rn, fe in freeze_ends.items():
        # Sample ~5 seconds after freeze_end (320 ticks at 64tick)
        # This gets players out of spawn and into their initial positions
        ENTRY_OFFSET_TICKS = 320  # ~5 seconds
        window = frame_df[
            (frame_df["round_num"] == rn) &
            (frame_df["tick"] >= fe + ENTRY_OFFSET_TICKS) &
            (frame_df["tick"] <= fe + ENTRY_OFFSET_TICKS + 64)
        ]
        if window.empty:
            # Fallback: use earliest available tick after freeze_end
            window = frame_df[
                (frame_df["round_num"] == rn) &
                (frame_df["tick"] >= fe)
            ]
            if window.empty:
                continue

        first_tick = window["tick"].min()
        tick_data  = window[window["tick"] == first_tick]

        for row in tick_data.itertuples(index=False):
            sid    = _safe_str(getattr(row, "steamid", ""))
            health = _safe_float(getattr(row, "health", 0))
            if not sid or health <= 0:
                continue

            x = round(_safe_float(getattr(row, "X", 0)), 1)
            y = round(_safe_float(getattr(row, "Y", 0)), 1)

            raw_side = str(getattr(row, side_col, "") or "").lower()
            side = "t" if raw_side in ("t", "terrorist") else \
                   "ct" if raw_side in ("ct", "counterterrorist") else None
            if side is None:
                continue

            result[sid].append({"x": x, "y": y, "s": side[0], "r": rn})

    return dict(result)


# ─── Main entry ───────────────────────────────────────────────────────────────

async def compute_spatial_data(
    pool:        aiomysql.Pool,
    demo_id:     int,
    frame_df:    pd.DataFrame,
    rounds_df:   pd.DataFrame,
    smokes_df:   pd.DataFrame,
    infernos_df: pd.DataFrame,
    grenades_df: pd.DataFrame,
    shots_df:    pd.DataFrame,
    planted_df:  pd.DataFrame,
) -> None:
    """
    Compute all spatial data types concurrently and store in demo_spatial.
    Non-fatal — any individual type failure is logged and skipped.
    """
    logger.info(f"[Spatial] Computing spatial data for demo {demo_id}")

    try:
        # Run all heavy computations in a thread pool (CPU-bound pandas work)
        loop = asyncio.get_event_loop()

        paths_data, utility_data, shots_data, plants_data, entries_data = await asyncio.gather(
            loop.run_in_executor(None, compute_paths,   frame_df, rounds_df),
            loop.run_in_executor(None, compute_utility, smokes_df, infernos_df, grenades_df),
            loop.run_in_executor(None, compute_shots,   shots_df),
            loop.run_in_executor(None, compute_plants,  planted_df, frame_df),
            loop.run_in_executor(None, compute_entries, frame_df, rounds_df),
        )

        datasets = {
            "paths":   paths_data,
            "utility": utility_data,
            "shots":   shots_data,
            "plants":  plants_data,
            "entries": entries_data,
        }

        # Store each type — upsert on (demo_id, type)
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                for dtype, data in datasets.items():
                    try:
                        compressed = _compress(data)
                        await cursor.execute(
                            """
                            INSERT INTO demo_spatial (demo_id, type, data, created_at, updated_at)
                            VALUES (%s, %s, %s, NOW(), NOW())
                            ON DUPLICATE KEY UPDATE data = VALUES(data), updated_at = NOW()
                            """,
                            (demo_id, dtype, compressed),
                        )
                        logger.info(f"[Spatial] Stored {dtype} for demo {demo_id}")
                    except Exception as e:
                        logger.warning(f"[Spatial] Failed to store {dtype} for demo {demo_id}: {e}")

            await conn.commit()

        logger.info(f"[Spatial] All spatial data stored for demo {demo_id}")

    except Exception as exc:
        logger.error(f"[Spatial] Spatial computation failed for demo {demo_id}: {exc}")