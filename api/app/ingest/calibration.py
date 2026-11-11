"""Calibration drift detection (Stage 12 §12.2).

When Valve reworks a map, the stored `pos_x/pos_y/scale` drift and every player position renders
wrong — silently. We catch that at parse: project a sample of real in-demo positions through the
resolved calibration and check they land on (or near) the radar image. If most of them fall way
outside, the calibration doesn't match this demo's map version → flag `calibration_suspect` so we
never ship a misaligned viewer. The same `world→image` transform the viewer uses (Stage 07).
"""
from __future__ import annotations

from typing import Any, Iterable

# Radar images are square; the world→pixel transform targets this px space (viewer assumes it too).
RADAR_SIZE = 1024


def world_to_image(map_row: dict, wx: float, wy: float) -> tuple[float, float]:
    scale = map_row.get("scale") or 1
    return ((wx - map_row["pos_x"]) / scale, (map_row["pos_y"] - wy) / scale)


def check_calibration(map_row: dict | None, positions: Iterable[tuple[float, float]],
                      *, radar_size: int = RADAR_SIZE, margin: float = 0.15,
                      min_inside: float = 0.6) -> dict[str, Any]:
    """Project sampled world positions and report how many land on/near the radar.

    `suspect` is True if fewer than `min_inside` of the (non-trivial) samples fall within the
    radar bounds expanded by `margin` — i.e. the calibration almost certainly doesn't fit. With
    no map row (unknown map) or no samples, it's not flagged (handled elsewhere).
    """
    pts = [(x, y) for x, y in positions if x is not None and y is not None]
    if map_row is None or not pts:
        return {"suspect": False, "checked": False, "in_bounds_fraction": None, "samples": len(pts)}

    lo = -margin * radar_size
    hi = radar_size * (1 + margin)
    inside = 0
    for wx, wy in pts:
        px, py = world_to_image(map_row, wx, wy)
        if lo <= px <= hi and lo <= py <= hi:
            inside += 1
    frac = inside / len(pts)
    return {
        "suspect": frac < min_inside,
        "checked": True,
        "in_bounds_fraction": round(frac, 3),
        "samples": len(pts),
        "map_version": map_row.get("version"),
    }


def sample_positions(ticks_df, limit: int = 200) -> list[tuple[float, float]]:
    """Pull a spread of player world positions from the ticks frame for the drift check."""
    if ticks_df is None or "X" not in getattr(ticks_df, "columns", []) or len(ticks_df) == 0:
        return []
    n = len(ticks_df)
    step = max(1, n // limit)
    sub = ticks_df.iloc[::step][["X", "Y"]]
    return [(float(x), float(y)) for x, y in sub.itertuples(index=False)
            if x is not None and y is not None]
