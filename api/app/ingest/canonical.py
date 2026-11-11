"""Canonical parquet archive — the warm re-derivation cache (Stage 10 + 14).

`Demo.compress()` writes awpy's dataframes but **omits** the bomb pickup/dropped/planted events
the payload builder relies on (and includes damages/footsteps we never use), so it can't fully
re-derive payloads. Instead we write our OWN canonical zip containing exactly the frames
`build_round_records` consumes — making the warm tier self-sufficient for the cheap re-derive
path (Stage 14 §14.1): read this back → `Frames` → rebuild payloads, no re-parse, no raw fetch.
"""
from __future__ import annotations

import io
import zipfile

import pandas as pd

from .rounds import Frames

# The Frames fields, in a stable member order. Names match `Frames` attributes exactly.
_MEMBERS = [
    "ticks", "rounds", "kills", "shots", "grenades", "smokes", "infernos",
    "bomb_pickup", "bomb_dropped", "bomb_planted",
]


def frames_to_zip(frames: Frames) -> bytes:
    """Serialize the parsed frames to a parquet zip (the canonical.zip stored on the warm tier)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in _MEMBERS:
            df = getattr(frames, name, None)
            if df is None:
                df = pd.DataFrame()
            pq = io.BytesIO()
            df.to_parquet(pq, index=False)
            zf.writestr(f"{name}.parquet", pq.getvalue())
    return buf.getvalue()


def frames_from_zip(data: bytes) -> Frames:
    """Inverse of frames_to_zip — load the canonical parquet zip back into Frames (re-derive)."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())

        def _read(member: str) -> pd.DataFrame:
            fn = f"{member}.parquet"
            if fn not in names:
                return pd.DataFrame()
            return pd.read_parquet(io.BytesIO(zf.read(fn)))

        return Frames(**{m: _read(m) for m in _MEMBERS})
