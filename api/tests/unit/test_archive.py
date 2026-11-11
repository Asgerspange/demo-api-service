"""Stage 05 — cold-archive zstd round-trip (the raw .dem must come back byte-identical)."""
import pytest

from app.ingest.archive import compress_raw, decompress_raw, raw_archive_key

pytestmark = pytest.mark.unit


def test_zstd_round_trip_byte_identical():
    raw = b"PBDEMS2\x00" + bytes(range(256)) * 2_000  # ~512 KB, compressible
    blob = compress_raw(raw)
    assert blob != raw
    assert len(blob) < len(raw)
    assert decompress_raw(blob) == raw


def test_zstd_round_trip_empty_and_small():
    for raw in (b"", b"PBDEMS2", b"\x00\x01\x02"):
        assert decompress_raw(compress_raw(raw)) == raw


def test_raw_archive_key():
    assert raw_archive_key(42) == "42/raw.dem.zst"


async def test_cold_archive_round_trip_through_object_store():
    """Stage 10 acceptance: a cold raw .dem stored compressed comes back byte-identical
    (compress → put → get → decompress), even on hard-to-compress (random) content."""
    import os

    raw = b"PBDEMS2\x00" + os.urandom(80_000)   # worst case: barely compressible
    blob = compress_raw(raw)

    # round-trip through an in-memory stand-in for the cold archive object store
    objects: dict[str, bytes] = {}
    objects[raw_archive_key(7)] = blob          # "upload"
    fetched = objects[raw_archive_key(7)]       # "download"

    assert decompress_raw(fetched) == raw        # byte-identical
