"""Phase 02 — per-round payload format (v1 gzipped JSON)."""
import gzip
import json
from pathlib import Path

import orjson
import pytest

from app.payload import (
    GRENADE_FIELDS,
    PAYLOAD_VERSION,
    PLAYER_FIELDS,
    PayloadError,
    build_index,
    decode_round,
    encode_round,
    validate_round,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "round_v1.json"


@pytest.fixture
def sample_round() -> dict:
    return json.loads(FIXTURE.read_text())


@pytest.mark.unit
def test_roundtrip_is_lossless(sample_round):
    blob = encode_round(sample_round)
    assert decode_round(blob) == sample_round


@pytest.mark.unit
def test_encoded_is_gzipped_json(sample_round):
    blob = encode_round(sample_round)
    # Real gzip member (magic 0x1f 0x8b) that ungzips to the same JSON object.
    assert blob[:2] == b"\x1f\x8b"
    assert json.loads(gzip.decompress(blob)) == sample_round


@pytest.mark.unit
def test_int_tick_keys_serialize_as_string_numbers():
    # demo_processor builds tick_dict keyed by int tick; the worker re-parses with Number().
    record = {
        "ticks": {100: {"players": None}},
        "meta": {}, "smokes": [], "infernos": [], "kills": {},
    }
    decoded = decode_round(encode_round(record))
    assert set(decoded["ticks"].keys()) == {"100"}


@pytest.mark.unit
def test_fixture_matches_worker_schema(sample_round):
    """The fixture round carries exactly the fields RoundLoader.worker.js reads."""
    validate_round(sample_round)  # must not raise

    # Spot-check the field contract the worker depends on.
    p = sample_round["ticks"]["100"]["players"][0]
    assert set(PLAYER_FIELDS).issubset(p.keys())
    g = sample_round["ticks"]["100"]["grenades"][0]
    assert set(GRENADE_FIELDS).issubset(g.keys())
    # C4 bit in inventory drives the worker's inventoryMask.
    assert "C4" in sample_round["ticks"]["100"]["players"][1]["inventory"]


@pytest.mark.unit
@pytest.mark.parametrize("drop", ["ticks", "meta", "smokes", "infernos", "kills"])
def test_validate_rejects_missing_top_level_key(sample_round, drop):
    sample_round.pop(drop)
    with pytest.raises(PayloadError):
        validate_round(sample_round)


@pytest.mark.unit
def test_validate_rejects_player_missing_field(sample_round):
    del sample_round["ticks"]["100"]["players"][0]["health"]
    with pytest.raises(PayloadError, match="health"):
        validate_round(sample_round)


@pytest.mark.unit
def test_validate_rejects_empty_ticks(sample_round):
    sample_round["ticks"] = {}
    with pytest.raises(PayloadError, match="non-empty"):
        validate_round(sample_round)


@pytest.mark.unit
def test_build_index_shape(sample_round):
    rounds = [
        {"round_index": 0, "storage_key": "7/v1/round-0.bin", "byte_size": 1234,
         "meta": {"winner": "ct"}},
        {"round_index": 1, "storage_key": "7/v1/round-1.bin", "byte_size": 2345,
         "meta": {"winner": "t"}},
    ]
    index = build_index(7, "de_mirage", rounds)
    assert index["payload_version"] == PAYLOAD_VERSION
    assert index["map"] == "de_mirage"
    assert index["map_ref"] == "/v1/maps/de_mirage"
    assert [r["round_index"] for r in index["rounds"]] == [0, 1]
    assert index["rounds"][0]["key"] == "7/v1/round-0.bin"
    # index must itself be JSON-serializable (it's stored as index.json).
    assert orjson.loads(orjson.dumps(index))["demo_id"] == 7
