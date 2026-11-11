"""Cold-tier archival of the raw `.dem` (Stage 5.2 step 5; detail in Stage 10).

The raw demo is the true source of truth for future re-parses, so we keep it forever in the
cold archive zone, zstd-compressed. The original plan called for `zstd --ultra -22 --long=31`,
but CS2 demos are already high-entropy — they compress only ~1.6x at *any* level — so the
ultra levels cost minutes of CPU for almost no extra ratio. We instead use a **fast,
multithreaded** level (configurable; default 10) with long-distance matching and a 128 MB
window (`window_log=27`). Recorded as `raw_codec='zstd'`. (Decompression only needs the
window size, set below.)
"""
from __future__ import annotations

import os

import zstandard as zstd

from ..config import settings

ZSTD_WINDOW_LOG = 27  # 128 MB long-distance-matching window (see module docstring)


def _threads() -> int:
    """Use all logical CPUs for compression (multithreaded zstd is the big win here)."""
    return max(1, os.cpu_count() or 1)


def compress_raw(data: bytes, *, level: int | None = None) -> bytes:
    """zstd-compress raw `.dem` bytes for cold storage (fast level + LDM, multithreaded)."""
    lvl = settings.ingest_archive_zstd_level if level is None else level
    params = zstd.ZstdCompressionParameters.from_level(
        lvl, enable_ldm=True, window_log=ZSTD_WINDOW_LOG, threads=_threads()
    )
    return zstd.ZstdCompressor(compression_params=params).compress(data)


def decompress_raw(blob: bytes) -> bytes:
    """Inverse of compress_raw — used by re-parse/backfill (Stage 14) and round-trip tests."""
    dctx = zstd.ZstdDecompressor(max_window_size=1 << ZSTD_WINDOW_LOG)
    return dctx.decompress(blob)


def raw_archive_key(demo_id: int) -> str:
    """Cold-archive object key for a demo's compressed raw `.dem`."""
    return f"{demo_id}/raw.dem.zst"
