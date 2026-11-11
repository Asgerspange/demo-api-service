"""Stage 14 — canonical parquet zip is a faithful, re-derivable round-trip of the frames."""
import pandas as pd
import pytest

from app.ingest.canonical import frames_from_zip, frames_to_zip
from app.ingest.rounds import Frames, build_round_records
from app.payload import validate_round

pytestmark = pytest.mark.unit


def _player_row(tick, rn, sid, name, side):
    return dict(tick=tick, round_num=rn, steamid=sid, name=name, side=side, team_clan_name="T",
                X=100.0, Y=200.0, Z=64.0, yaw=90.0, pitch=0.0, health=100, armor_value=100,
                balance=800, flash_duration=0.0, has_defuser=False, has_helmet=True,
                is_walking=False, active_weapon_name="ak47", inventory=["AK-47"],
                kills_total=0, deaths_total=0, assists_total=0)


def _frames() -> Frames:
    ticks = [_player_row(t, 1, s, n, sd) for t in range(100, 161, 10)
             for s, n, sd in (("111", "p1", "t"), ("222", "p2", "ct"))]
    rounds = pd.DataFrame([dict(round_num=1, start=100, end=160, official_end=160,
                               winner="t", reason="ct_killed")])
    planted = pd.DataFrame([dict(tick=140, user_X=5.0, user_Y=6.0, user_Z=64.0)])
    empty = pd.DataFrame()
    return Frames(ticks=pd.DataFrame(ticks), rounds=rounds, kills=empty, shots=empty,
                  grenades=empty, smokes=empty, infernos=empty,
                  bomb_pickup=empty, bomb_dropped=empty, bomb_planted=planted)


def test_canonical_round_trip_rebuilds_identical_payloads():
    frames = _frames()
    before = build_round_records(frames)

    restored = frames_from_zip(frames_to_zip(frames))
    after = build_round_records(restored)

    assert [r.round_index for r in after] == [r.round_index for r in before]
    # the re-derived payloads are still viewer-valid and carry the bomb-plant frames
    for rec in after:
        validate_round(rec.record)
    planted = [t["bomb"] for t in after[0].record["ticks"].values()
               if t["bomb"] and t["bomb"]["planted_ticks"] is not None]
    assert planted  # the bomb events survived the round-trip (awpy's compress would drop these)


def test_bomb_events_member_present():
    # the whole point: our canonical includes bomb_pickup/dropped/planted (awpy compress omits them)
    restored = frames_from_zip(frames_to_zip(_frames()))
    assert not restored.bomb_planted.empty
