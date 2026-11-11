"""Stage 11 — pre-parse classification: CS2-only, GOTV-only, reject CSGO + POV before parsing."""
import pytest

from app.ingest.classify import classify_header
from app.ingest.errors import UnsupportedDemoError

pytestmark = pytest.mark.unit


def _hdr(**over):
    h = {"demo_file_stamp": "PBDEMS2\x00", "demo_version_name": "valve_demo_2",
         "client_name": "SourceTV Demo", "map_name": "de_inferno"}
    h.update(over)
    return h


def test_gotv_cs2_classifies():
    c = classify_header(_hdr())
    assert c.map_name == "de_inferno" and c.is_gotv and c.demo_type == "gotv"


def test_classifies_via_version_name_when_stamp_missing():
    c = classify_header(_hdr(demo_file_stamp=""))
    assert c.is_gotv and c.map_name == "de_inferno"


def test_csgo_rejected_pre_parse():
    with pytest.raises(UnsupportedDemoError, match="CSGO|CS2 only"):
        classify_header(_hdr(demo_file_stamp="HL2DEMO\x00", demo_version_name="valve_demo"))


def test_pov_rejected_pre_parse():
    # a CS2 demo that isn't SourceTV → client-recorded POV → reject (no wasted parse)
    with pytest.raises(UnsupportedDemoError, match="POV"):
        classify_header(_hdr(client_name="s1mple"))


def test_non_cs2_rejected():
    with pytest.raises(UnsupportedDemoError, match="not CS2"):
        classify_header(_hdr(demo_file_stamp="OTHER", demo_version_name="something"))


def test_missing_map_rejected():
    with pytest.raises(UnsupportedDemoError, match="map_name"):
        classify_header(_hdr(map_name=""))
