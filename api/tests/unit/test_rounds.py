"""Stage 05 — build_round_records produces viewer-valid v1 payloads from awpy-shaped frames.

Uses small synthetic pandas frames (no real parse) so the pure transform is tested fast and
deterministically. The contract asserted is `app/payload.py` (what RoundLoader.worker.js reads).
"""
import pandas as pd
import pytest

from types import SimpleNamespace

from app.ingest.rounds import Frames, build_parse_report, build_round_records, reason_label
from app.payload import decode_round, encode_round, validate_round

pytestmark = pytest.mark.unit


def _player_row(tick, round_num, steamid, name, side, **over):
    row = dict(
        tick=tick, round_num=round_num, steamid=steamid, name=name, side=side,
        team_clan_name="TeamX", X=100.0 + tick, Y=200.0 - tick, Z=64.0, yaw=90.0, pitch=0.0,
        health=100, armor_value=100, balance=800, flash_duration=0.0,
        has_defuser=False, has_helmet=True, is_walking=False,
        active_weapon_name="ak47", inventory=["AK-47"],
        kills_total=0, deaths_total=0, assists_total=0,
    )
    row.update(over)
    return row


def _make_frames() -> Frames:
    ticks = []
    # Round 1: ticks 100..160 ; Round 2: ticks 300..360. 't' player listed first each tick.
    for rn, lo, hi in ((1, 100, 160), (2, 300, 360)):
        for t in range(lo, hi + 1, 5):
            ticks.append(_player_row(t, rn, "111", "p1", "t"))
            ticks.append(_player_row(t, rn, "222", "p2", "ct"))
    ticks_df = pd.DataFrame(ticks)

    rounds_df = pd.DataFrame([
        dict(round_num=1, start=100, end=160, official_end=160, winner="t", reason="elimination"),
        dict(round_num=2, start=300, end=360, official_end=360, winner="ct", reason="bomb_defused"),
    ])

    kills_df = pd.DataFrame([dict(
        tick=150, round_num=1, attacker_steamid="111", attacker_name="p1", attacker_side="t",
        victim_steamid="222", victim_name="p2", victim_side="ct", assister_steamid=None,
        assister_side=None, headshot=True, thrusmoke=False, assistedflash=False,
        attackerblind=False, attackerinair=False, noscope=False, weapon="ak47", hitgroup="head",
        attacker_X=150.0, attacker_Y=50.0, victim_X=160.0, victim_Y=60.0,
    )])

    shots_df = pd.DataFrame([dict(
        tick=140, round_num=1, weapon="ak47", player_steamid="111", player_name="p1",
        player_yaw=45.0, player_X=140.0, player_Y=60.0,
    )])

    grenades_df = pd.DataFrame([
        dict(entity_id=5, round_num=1, tick=145, thrower="p1", thrower_steamid="111",
             grenade_type="smoke", X=150.0, Y=55.0, Z=64.0),
        dict(entity_id=5, round_num=1, tick=147, thrower="p1", thrower_steamid="111",
             grenade_type="smoke", X=170.0, Y=45.0, Z=64.0),
    ])

    smokes_df = pd.DataFrame([dict(
        entity_id=5, round_num=1, start_tick=148, end_tick=160, thrower_name="p1",
        thrower_side="t", thrower_steamid="111", X=170.0, Y=45.0, Z=64.0,
    )])

    planted_df = pd.DataFrame([dict(tick=330, user_X=500.0, user_Y=600.0, user_Z=64.0)])
    empty = pd.DataFrame()

    return Frames(
        ticks=ticks_df, rounds=rounds_df, kills=kills_df, shots=shots_df,
        grenades=grenades_df, smokes=smokes_df, infernos=empty,
        bomb_pickup=empty, bomb_dropped=empty, bomb_planted=planted_df,
    )


def test_build_round_records_count_and_order():
    recs = build_round_records(_make_frames())
    assert [r.round_index for r in recs] == [1, 2]


def test_each_record_is_valid_v1_payload():
    for rec in build_round_records(_make_frames()):
        validate_round(rec.record)               # raises PayloadError if not viewer-shaped
        assert decode_round(encode_round(rec.record)).keys() >= {"ticks", "meta", "smokes", "infernos", "kills"}


def test_player_fields_and_team_name_rename():
    rec = build_round_records(_make_frames())[0]
    some_tick = next(iter(rec.record["ticks"].values()))
    player = some_tick["players"][0]
    assert player["team_name"] in ("t", "ct")     # side → team_name
    assert "side" not in player
    assert set(player) >= {"steamid", "name", "X", "Y", "yaw", "health", "armor_value",
                           "flash_duration", "has_defuser", "has_helmet", "is_walking",
                           "active_weapon_name", "inventory", "balance"}


def test_smoke_and_grenade_and_killfeed():
    r1 = build_round_records(_make_frames())[0].record
    assert r1["smokes"] and r1["smokes"][0]["entity_id"] == 5
    # grenade trajectory lands on its tick
    assert any(t["grenades"] for t in r1["ticks"].values())
    # kill recorded in meta killfeed + full kills map
    assert r1["meta"]["kills"]
    assert r1["kills"]


def test_bomb_planted_appears_in_ticks():
    r2 = build_round_records(_make_frames())[1].record
    planted = [t["bomb"] for t in r2["ticks"].values()
               if t["bomb"] and t["bomb"]["planted_ticks"] is not None]
    assert planted, "expected planted bomb positions in round 2"
    assert planted[0]["X"] == 500.0


def test_scoreline_progresses():
    recs = build_round_records(_make_frames())
    # each side wins one round → both scores reach 1 by the end
    last = recs[-1].light_meta
    assert last["T_score"] == 1 and last["CT_score"] == 1
    assert recs[0].light_meta["n_ticks"] > 0


# ── Stage 11 hardening ──────────────────────────────────────────────────────────────────

def test_reason_label_maps_and_degrades():
    assert reason_label("ct_killed") == "Counter-Terrorists eliminated"
    assert reason_label("bomb_defused") == "Bomb defused"
    assert reason_label(7) == "Bomb defused"               # legacy int enum
    assert reason_label("some_new_reason") == "Some new reason"  # unknown → readable, no crash
    assert reason_label(None) == "Round over"


def test_reason_label_in_round_meta():
    rec = build_round_records(_make_frames())[0]   # round 1 reason='elimination' → readable fallback
    assert rec.record["meta"]["reason_label"] == "Elimination"
    assert rec.light_meta["reason_label"] == "Elimination"


def test_non_participants_are_filtered_out():
    frames = _make_frames()
    # inject a coach/spectator (side='') and a caster (side='spectator') into round 1
    extra = pd.DataFrame([
        _player_row(100, 1, "999", "coach", ""),
        _player_row(100, 1, "888", "caster", "spectator"),
    ])
    frames.ticks = pd.concat([frames.ticks, extra], ignore_index=True)
    rec = build_round_records(frames)[0]
    seen = {p["steamid"] for tick in rec.record["ticks"].values() for p in tick["players"]}
    assert "999" not in seen and "888" not in seen
    assert {"111", "222"} <= seen


def test_parse_report_summarizes_demo():
    frames = _make_frames()
    recs = build_round_records(frames)
    cls = SimpleNamespace(demo_type="gotv", is_gotv=True, tickrate=64,
                          map_name="de_inferno", demo_version="valve_demo_2")
    report = build_parse_report(cls, frames, recs)
    assert report["demo_type"] == "gotv" and report["map"] == "de_inferno"
    assert report["rounds_found"] == 2 and report["rounds_expected"] == 2
    assert report["player_count"] == 2
    # only 2 players (not 10) → flagged as an anomaly
    assert any("players" in a for a in report["anomalies"])


def test_build_scoreboard_counts_from_killfeed():
    from app.ingest.rounds import build_scoreboard

    # Ticks supply team/name/damage; the killfeed supplies K/D/A/HS.
    ticks = [
        _player_row(100, 1, "111", "ace", "t", damage_total=100),
        _player_row(100, 1, "222", "sup", "ct", damage_total=20),
        _player_row(300, 2, "111", "ace", "t", damage_total=380),
        _player_row(300, 2, "222", "sup", "ct", damage_total=150),
        _player_row(300, 2, "999", "coach", "spectator"),   # excluded (not t/ct)
    ]
    # ace(111): 2 kills (1 hs), 1 death, 1 assist ; sup(222): 1 kill, 3 deaths, 0 assists.
    kills = pd.DataFrame([
        dict(attacker_steamid="111", victim_steamid="222", assister_steamid=None, headshot=True),
        dict(attacker_steamid="111", victim_steamid="222", assister_steamid=None, headshot=False),
        dict(attacker_steamid="222", victim_steamid="111", assister_steamid="111", headshot=False),
        dict(attacker_steamid="222", victim_steamid="222", assister_steamid=None, headshot=False),  # suicide → not a frag
    ])
    frames = SimpleNamespace(ticks=pd.DataFrame(ticks), kills=kills)

    board = build_scoreboard(frames, rounds=2)

    assert [p["steamid"] for p in board] == ["111", "222"]      # sorted by kills desc
    ace = board[0]
    assert ace["kills"] == 2 and ace["deaths"] == 1 and ace["assists"] == 1
    assert ace["hs"] == 50                                       # 1 hs / 2 kills
    assert ace["adr"] == 190.0                                  # 380 damage / 2 rounds
    assert ace["team"] == "t" and ace["name"] == "ace"
    sup = board[1]
    assert sup["kills"] == 1 and sup["deaths"] == 3 and sup["assists"] == 0  # suicide not a frag, but is a death
    assert all(p["steamid"] != "999" for p in board)            # spectator filtered out


def test_build_scoreboard_empty_frames():
    from app.ingest.rounds import build_scoreboard

    frames = SimpleNamespace(ticks=pd.DataFrame())
    board = build_scoreboard(frames, rounds=1)
    assert board == []
