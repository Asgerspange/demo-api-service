"""Stage 18 §18.2 — multi-part demo reassembly."""
import pytest

from app.ingest.parts import parse_part, reassemble

pytestmark = pytest.mark.unit


def test_parse_part_recognizes_suffixes():
    assert parse_part("match_p1.dem") == ("match", 1)
    assert parse_part("match-p02.dem") == ("match", 2)
    assert parse_part("dir/match.part3.dem") == ("match", 3)
    assert parse_part("match_part10.dem") == ("match", 10)
    assert parse_part("de_nuke.dem") is None        # no part suffix
    assert parse_part("p1.dem") is None             # nothing before the marker


def test_reassemble_concatenates_parts_in_order():
    members = [
        ("match_p2.dem", b"BBB"),
        ("match_p1.dem", b"PBDEMS2-AAA"),
        ("match_p3.dem", b"CCC"),
    ]
    out = reassemble(members)
    assert len(out) == 1
    name, data = out[0]
    assert name == "match.dem"
    assert data == b"PBDEMS2-AAA" + b"BBB" + b"CCC"   # sorted by part number, header from part 1


def test_reassemble_passes_through_whole_demos():
    members = [("de_nuke.dem", b"PBDEMS2-n"), ("de_mirage.dem", b"PBDEMS2-m")]
    out = reassemble(members)
    assert sorted(n for n, _ in out) == ["de_mirage.dem", "de_nuke.dem"]


def test_lone_part_is_treated_as_a_whole():
    out = reassemble([("solo_p1.dem", b"PBDEMS2-solo")])
    assert out == [("solo_p1.dem", b"PBDEMS2-solo")]    # one part → not a fragment


def test_distinct_bases_stay_separate():
    # the user's example: demo1_p1 + demo2_p2 are different bases → two demos, not one
    out = reassemble([("demo1_p1.dem", b"PBDEMS2-1"), ("demo2_p2.dem", b"PBDEMS2-2")])
    assert len(out) == 2


def test_mixed_parts_and_wholes():
    members = [
        ("de_nuke.dem", b"PBDEMS2-nuke"),
        ("split_p1.dem", b"PBDEMS2-a"),
        ("split_p2.dem", b"b"),
    ]
    out = reassemble(members)
    names = {n for n, _ in out}
    assert names == {"de_nuke.dem", "split.dem"}
    split = dict(out)["split.dem"]
    assert split == b"PBDEMS2-a" + b"b"
