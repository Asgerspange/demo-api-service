"""Per-round viewer payload format — the contract shared by the parser (writer, Stage 05)
and the viewer (reader, Stage 07).

**v1 = gzipped JSON**, byte-identical in shape to the proven old system: the
`{ticks, meta, smokes, infernos, kills}` record that `demo_processor._process_single_round`
produced, decoded client-side into columnar TypedArrays by `RoundLoader.worker.js`. The
field sets below are transcribed from that worker (the reader) so a fixture round can be
checked against them — if the worker reads a field, it's listed here.

A future v2 (pre-columnarized binary) ships behind the same `/rounds/{i}` endpoint; the
viewer negotiates via `index.json`'s `payload_version`. Keep this module the single source
of truth for both versions.
"""
from __future__ import annotations

import gzip
from typing import Any, Mapping

import orjson

PAYLOAD_VERSION = 1

# Per-round payloads are immutable CDN-cached artifacts: we pay compression CPU **once** at
# ingest (async/batched) and it shrinks every future viewer download + storage forever. So a
# stronger level than the old system's `1` is the right default — 6 is gzip's standard balance
# (most of 9's ratio for a fraction of the CPU). Decode is level-agnostic, so changing this is
# NOT a payload_version bump. Overridable via settings for tuning.
DEFAULT_GZIP_LEVEL = 6

# Top-level keys of a round record (what RoundLoader.worker.js reads as `data.*`, plus
# `infernos` which the writer emits alongside `smokes`).
TOP_LEVEL_KEYS = ("ticks", "meta", "smokes", "infernos", "kills")

# Per-player fields the worker reads when filling its columnar arrays (see the
# `col.* = p.*` assignments in RoundLoader.worker.js). `inventory` is a list containing
# 'C4' when the player carries the bomb (worker derives inventoryMask bit0 from it).
PLAYER_FIELDS = (
    "steamid", "name", "X", "Y", "yaw", "health", "armor_value", "balance",
    "flash_duration", "has_defuser", "has_helmet", "is_walking",
    "active_weapon_name", "team_name", "inventory",
)

# Sparse per-tick structures (present only on ticks that have them).
BOMB_FIELDS = ("X", "Y", "planted_ticks")
WEAPON_FIRE_FIELDS = ("player_steamid", "player_X", "player_Y", "player_yaw", "weapon")
GRENADE_FIELDS = ("entity_id", "grenade_type", "X", "Y", "thrower_steamid")

_DUMP_OPTS = orjson.OPT_NON_STR_KEYS | orjson.OPT_SERIALIZE_NUMPY


def _encode_default(obj: Any) -> Any:
    """Fallback for stray numpy/pandas types orjson can't natively serialize.

    `OPT_SERIALIZE_NUMPY` handles numeric numpy *scalars/arrays* fast, but anything outside
    that (a lone `numpy.generic`, an object-dtype value, a `pandas` NA) routes here. Object
    *arrays* must be flattened upstream (the writer does), since orjson won't route those to
    `default` — this is a safety net for scalars.
    """
    import numpy as np

    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    try:
        import pandas as pd

        if obj is pd.NaT or (not isinstance(obj, (list, dict)) and pd.isna(obj)):
            return None
    except (ImportError, ValueError, TypeError):
        pass
    raise TypeError(f"unserializable type in round payload: {type(obj)}")


# --- encode / decode -------------------------------------------------------------------

def encode_round(record: Mapping[str, Any], *, level: int = DEFAULT_GZIP_LEVEL) -> bytes:
    """Serialize a round record to the v1 wire format (gzipped JSON).

    Tick dicts are keyed by integer tick number; OPT_NON_STR_KEYS emits them as the JSON
    string keys the worker re-parses with `Number(...)`. `level` is the gzip level (see
    DEFAULT_GZIP_LEVEL) — higher shrinks the CDN-served bytes at one-time ingest CPU cost.
    """
    return gzip.compress(
        orjson.dumps(record, default=_encode_default, option=_DUMP_OPTS), compresslevel=level
    )


def decode_round(blob: bytes) -> dict[str, Any]:
    """Inverse of encode_round — gunzip + JSON parse. (Mirrors the viewer's fetch path.)"""
    return orjson.loads(gzip.decompress(blob))


# --- validation ------------------------------------------------------------------------

class PayloadError(ValueError):
    """A round record does not match the v1 schema the viewer expects."""


def validate_round(record: Mapping[str, Any]) -> None:
    """Raise PayloadError if `record` is not a well-formed v1 round payload.

    Checks the contract the viewer relies on: the five top-level keys, a non-empty
    tick map, and the required field set on each player / bomb / weapon-fire / grenade.
    """
    missing = [k for k in TOP_LEVEL_KEYS if k not in record]
    if missing:
        raise PayloadError(f"missing top-level keys: {missing}")

    ticks = record["ticks"]
    if not isinstance(ticks, Mapping) or not ticks:
        raise PayloadError("`ticks` must be a non-empty map keyed by tick number")

    for tick_key, tick in ticks.items():
        where = f"ticks[{tick_key}]"
        if not isinstance(tick, Mapping):
            raise PayloadError(f"{where} must be an object")
        players = tick.get("players")
        if players is None:
            continue  # a tick may legitimately have no players snapshot
        if not isinstance(players, list):
            raise PayloadError(f"{where}.players must be a list")
        for i, p in enumerate(players):
            _require_fields(p, PLAYER_FIELDS, f"{where}.players[{i}]")
        if "bomb" in tick and tick["bomb"] is not None:
            _require_fields(tick["bomb"], BOMB_FIELDS, f"{where}.bomb")
        for i, wf in enumerate(tick.get("weapon_fires", []) or []):
            _require_fields(wf, WEAPON_FIRE_FIELDS, f"{where}.weapon_fires[{i}]")
        for i, g in enumerate(tick.get("grenades", []) or []):
            _require_fields(g, GRENADE_FIELDS, f"{where}.grenades[{i}]")


def _require_fields(obj: Any, fields: tuple[str, ...], where: str) -> None:
    if not isinstance(obj, Mapping):
        raise PayloadError(f"{where} must be an object")
    missing = [f for f in fields if f not in obj]
    if missing:
        raise PayloadError(f"{where} missing fields: {missing}")


# --- index.json ------------------------------------------------------------------------

def build_index(
    demo_id: int,
    map_name: str,
    rounds: list[Mapping[str, Any]],
    *,
    payload_version: int = PAYLOAD_VERSION,
    api_version: str = "v1",
) -> dict[str, Any]:
    """Build the per-demo `index.json` (round list + map + scale ref + payload_version).

    `rounds` items carry at least `round_index`, `storage_key`, `byte_size`; the lightweight
    round `meta` (score/reason/ticks) is passed through when present. `map_ref` points the
    viewer at `/v1/maps/{map}` for calibration + radar URL (Stage 06).
    """
    return {
        "payload_version": payload_version,
        "demo_id": demo_id,
        "map": map_name,
        "map_ref": f"/{api_version}/maps/{map_name}",
        "rounds": [
            {
                "round_index": r["round_index"],
                "key": r["storage_key"],
                "byte_size": r["byte_size"],
                "meta": r.get("meta"),
            }
            for r in rounds
        ],
    }
