"""Stage 13 §13.4 — steam-id anonymization: no real ids, stable per-demo aliases."""
import pandas as pd
import pytest

from app.ingest.privacy import anonymize_frames, build_alias_maps
from app.ingest.rounds import Frames, build_round_records
from app.payload import validate_round

pytestmark = pytest.mark.unit

REAL_IDS = {"111", "222"}


def _player_row(tick, round_num, steamid, name, side):
    return dict(
        tick=tick, round_num=round_num, steamid=steamid, name=name, side=side,
        team_clan_name="TeamX", X=100.0, Y=200.0, Z=64.0, yaw=90.0, pitch=0.0,
        health=100, armor_value=100, balance=800, flash_duration=0.0,
        has_defuser=False, has_helmet=True, is_walking=False,
        active_weapon_name="ak47", inventory=["AK-47"],
        kills_total=0, deaths_total=0, assists_total=0,
    )


def _make_frames() -> Frames:
    ticks = []
    for rn, lo, hi in ((1, 100, 160), (2, 300, 360)):
        for t in range(lo, hi + 1, 10):
            ticks.append(_player_row(t, rn, "111", "p1", "t"))
            ticks.append(_player_row(t, rn, "222", "p2", "ct"))
    rounds_df = pd.DataFrame([
        dict(round_num=1, start=100, end=160, official_end=160, winner="t", reason="elimination"),
        dict(round_num=2, start=300, end=360, official_end=360, winner="ct", reason="bomb_defused"),
    ])
    kills_df = pd.DataFrame([dict(
        tick=150, round_num=1, attacker_steamid="111", attacker_name="p1", attacker_side="t",
        victim_steamid="222", victim_name="p2", victim_side="ct", assister_steamid=None,
        assister_side=None, headshot=True, weapon="ak47", hitgroup="head",
        attacker_X=150.0, attacker_Y=50.0, victim_X=160.0, victim_Y=60.0,
    )])
    empty = pd.DataFrame()
    return Frames(ticks=pd.DataFrame(ticks), rounds=rounds_df, kills=kills_df, shots=empty,
                  grenades=empty, smokes=empty, infernos=empty,
                  bomb_pickup=empty, bomb_dropped=empty, bomb_planted=empty)


def test_alias_maps_are_stable_and_opaque():
    frames = _make_frames()
    sid_alias, name_alias = build_alias_maps(frames)
    assert set(sid_alias) == REAL_IDS
    assert all(not v.isdigit() or not v.startswith("7656") for v in sid_alias.values())
    # deterministic: same input → same mapping
    assert build_alias_maps(_make_frames())[0] == sid_alias


def test_anonymized_records_contain_no_real_steamids():
    frames = anonymize_frames(_make_frames())
    recs = build_round_records(frames)
    blob = " ".join(
        p["steamid"]
        for rec in recs for tick in rec.record["ticks"].values() for p in tick["players"]
    )
    assert REAL_IDS.isdisjoint(blob.split())
    # players still present (just aliased) and the payload is still viewer-valid
    for rec in recs:
        validate_round(rec.record)
    some = next(iter(recs[0].record["ticks"].values()))["players"][0]
    assert some["steamid"].startswith("anon")


def test_aliases_consistent_across_rounds():
    frames = anonymize_frames(_make_frames())
    recs = build_round_records(frames)
    # the same real player keeps the same alias in round 1 and round 2
    alias_by_name = {}
    for rec in recs:
        for tick in rec.record["ticks"].values():
            for p in tick["players"]:
                alias_by_name.setdefault(p["name"], set()).add(p["steamid"])
    assert all(len(v) == 1 for v in alias_by_name.values())
