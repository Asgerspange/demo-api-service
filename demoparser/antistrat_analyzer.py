"""
antistrat_analyzer.py

Post-processing step that runs after a demo is fully parsed.
Detects rule-based patterns from positional/kill data and optionally
calls the Odin AI (OpenAI-compatible) for natural language summaries.

Called from demo_processor.py after _process_demo_data completes.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import aiomysql
import aiohttp
from loguru import logger


# ─── Config ───────────────────────────────────────────────────────────────────

ODIN_BASE_URL: str = os.getenv("ODIN_BASE_URL", "https://api.ordbogen.ai/v1")
ODIN_API_KEY: str  = os.getenv("ODIN_API_KEY", "")
ODIN_MODEL: str    = os.getenv("ODIN_MODEL", "odin-medium")

# How many pixels from spawn before a player is considered "out" in the first 5s
FAST_RUSH_THRESHOLD_SECONDS: float = 8.0
# Fraction of team that must cross threshold to count as a rush
FAST_RUSH_TEAM_FRACTION: float = 0.6


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class RoundPattern:
    round_num: int
    side: str                       # "t" | "ct"
    pattern: str                    # "fast_rush" | "default" | "eco_aggression" | "split"
    confidence: float               # 0.0 – 1.0
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class TeamPatterns:
    clan_name: str
    steamids: list[str]
    rounds_analyzed: int
    fast_rush_rate: float           # 0.0 – 1.0
    eco_aggression_rate: float
    avg_first_contact_second: float
    map: str
    round_patterns: list[RoundPattern] = field(default_factory=list)


# ─── Rule-based detector ──────────────────────────────────────────────────────

def detect_round_patterns(
    frame_df,   # pandas DataFrame
    kills_df,   # pandas DataFrame
    rounds_meta: list[dict],
) -> tuple[TeamPatterns, TeamPatterns]:
    """
    Analyse frame_df and kills_df to extract tactical patterns per team.

    Returns (team_a_patterns, team_b_patterns) where team_a is the T-side
    starting team and team_b is CT.
    """
    import pandas as pd

    rounds_by_num = {r["round_num"]: r for r in rounds_meta}
    team_a_patterns: list[RoundPattern] = []
    team_b_patterns: list[RoundPattern] = []

    # Identify team compositions from round 1
    r1 = frame_df[frame_df["round_num"] == 1]
    if r1.empty:
        empty_tp = TeamPatterns("Unknown", [], 0, 0.0, 0.0, 0.0, "unknown")
        return empty_tp, empty_tp

    team_a_ids = set(r1[r1["side"] == "t"]["steamid"].astype(str).unique())
    team_b_ids = set(r1[r1["side"] == "ct"]["steamid"].astype(str).unique())
    team_a_name = r1[r1["side"] == "t"]["team_clan_name"].iloc[0] if not r1[r1["side"] == "t"].empty else "Team A"
    team_b_name = r1[r1["side"] == "ct"]["team_clan_name"].iloc[0] if not r1[r1["side"] == "ct"].empty else "Team B"
    map_name    = frame_df["map_name"].iloc[0] if "map_name" in frame_df.columns else "unknown"

    total_rounds = 0

    for round_num, round_data in frame_df.groupby("round_num"):
        r_info = rounds_by_num.get(round_num)
        if r_info is None:
            continue

        total_rounds += 1
        tick_start: int = r_info.get("start", 0)
        freeze_end: int = r_info.get("freeze_end", tick_start + 256)  # ~4s at 64 tick

        # ── Fast rush detection ──────────────────────────────────────────────
        # Look at T-side positions within first FAST_RUSH_THRESHOLD_SECONDS
        ticks_per_second = 64  # standard matchmaking
        rush_end_tick = freeze_end + int(FAST_RUSH_THRESHOLD_SECONDS * ticks_per_second)

        early_frames = round_data[
            (round_data["tick"] >= freeze_end) &
            (round_data["tick"] <= rush_end_tick)
        ]

        t_early = early_frames[early_frames["side"] == "t"]
        if not t_early.empty:
            # Use kills in that window as a proxy for aggression
            early_kills = kills_df[
                (kills_df["round_num"] == round_num) &
                (kills_df["tick"] <= rush_end_tick)
            ]

            t_early_kills = early_kills[
                early_kills["attacker_steamid"].astype(str).isin(team_a_ids)
            ]

            if len(t_early_kills) >= 2:
                team_a_patterns.append(RoundPattern(
                    round_num=int(round_num),
                    side="t",
                    pattern="fast_rush",
                    confidence=min(1.0, len(t_early_kills) / 3),
                    evidence={"early_kills": int(len(t_early_kills))},
                ))

        # ── Eco aggression detection ─────────────────────────────────────────
        # Eco = team equipment value below threshold, yet they take fights
        t_frames = round_data[round_data["side"] == "t"]
        if not t_frames.empty and "equipment_value_total" in t_frames.columns:
            avg_eq = t_frames.groupby("steamid")["equipment_value_total"].max().mean()

            if avg_eq < 2000:  # eco threshold
                round_kills_t = kills_df[
                    (kills_df["round_num"] == round_num) &
                    (kills_df["attacker_steamid"].astype(str).isin(team_a_ids))
                ]
                if len(round_kills_t) >= 2:
                    team_a_patterns.append(RoundPattern(
                        round_num=int(round_num),
                        side="t",
                        pattern="eco_aggression",
                        confidence=0.8,
                        evidence={"avg_equipment": float(avg_eq), "kills": int(len(round_kills_t))},
                    ))

    # ── Aggregate rates ──────────────────────────────────────────────────────
    def _rate(patterns: list[RoundPattern], pattern_type: str, n: int) -> float:
        if n == 0:
            return 0.0
        return round(sum(1 for p in patterns if p.pattern == pattern_type) / n, 3)

    tp_a = TeamPatterns(
        clan_name=str(team_a_name),
        steamids=list(team_a_ids),
        rounds_analyzed=total_rounds,
        fast_rush_rate=_rate(team_a_patterns, "fast_rush", total_rounds),
        eco_aggression_rate=_rate(team_a_patterns, "eco_aggression", total_rounds),
        avg_first_contact_second=0.0,
        map=str(map_name),
        round_patterns=team_a_patterns,
    )
    tp_b = TeamPatterns(
        clan_name=str(team_b_name),
        steamids=list(team_b_ids),
        rounds_analyzed=total_rounds,
        fast_rush_rate=_rate(team_b_patterns, "fast_rush", total_rounds),
        eco_aggression_rate=_rate(team_b_patterns, "eco_aggression", total_rounds),
        avg_first_contact_second=0.0,
        map=str(map_name),
        round_patterns=team_b_patterns,
    )

    return tp_a, tp_b


# ─── Opponent matching ────────────────────────────────────────────────────────

async def find_opponent_match(
    pool: aiomysql.Pool,
    user_id: int,
    team_ids: list[int],
    clan_name: str,
    steamids: list[str],
) -> int | None:
    """
    Try to match a parsed team to an existing opponent_team record visible to
    the uploading user — profiles they own, plus any shared with a team they
    belong to.

    Matching strategy (in priority order):
      1. Steamid overlap  — ≥2 known steamids match opponent_team_players
      2. Clan name match  — similar_text equivalent (>=60% similarity)

    Returns opponent_team_id or None.
    """
    if not user_id:
        return None

    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            # Visible = owned by the user, or shared with one of their teams
            params: list = [user_id]
            share_clause = ""
            if team_ids:
                placeholders = ",".join(["%s"] * len(team_ids))
                share_clause = (
                    f" OR ot.id IN (SELECT opponent_team_id FROM opponent_team_shares "
                    f"WHERE team_id IN ({placeholders}))"
                )
                params.extend(team_ids)

            await cursor.execute(
                f"""
                SELECT ot.id, ot.name,
                       GROUP_CONCAT(otp.steamid) AS steamids
                FROM opponent_teams ot
                LEFT JOIN opponent_team_players otp ON otp.opponent_team_id = ot.id
                WHERE (ot.user_id = %s{share_clause})
                  AND ot.deleted_at IS NULL
                GROUP BY ot.id
                """,
                params,
            )
            opponents = await cursor.fetchall()

    best_id    = None
    best_score = 0

    steamids_set = set(str(s) for s in steamids if s)

    for opp in opponents:
        score = 0

        # Steamid overlap
        known_ids = set(filter(None, (opp["steamids"] or "").split(",")))
        overlap   = len(steamids_set & known_ids)
        score    += overlap * 20

        # Name similarity (simplified ratio)
        opp_name  = (opp["name"] or "").lower().strip()
        clan_norm = clan_name.lower().strip()
        if opp_name and clan_norm:
            shorter = min(len(opp_name), len(clan_norm))
            longer  = max(len(opp_name), len(clan_norm))
            common  = sum(c1 == c2 for c1, c2 in zip(opp_name[:shorter], clan_norm[:shorter]))
            ratio   = (common / longer * 100) if longer else 0
            score  += ratio * 0.5

        if score > best_score and score >= 20:
            best_score = score
            best_id    = opp["id"]

    logger.info(f"Opponent match for '{clan_name}': id={best_id} score={best_score}")
    return best_id


async def upsert_suggestion(
    pool: aiomysql.Pool,
    user_id: int,
    demo_id: int,
    clan_name: str,
    steamids: list[str],
    player_names: list[str],
    map_name: str,
) -> None:
    """
    Store an unmatched team as a suggestion so the user can create an opponent
    profile from it in the UI. Uses INSERT ... ON DUPLICATE KEY UPDATE so
    repeated demos from the same clan just refresh the steamid/player list.
    One suggestion per (user_id, clan_name).
    """
    if not clan_name or not user_id:
        return

    steamids_json = json.dumps([str(s) for s in steamids if s])
    names_json    = json.dumps(player_names)

    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            try:
                await cursor.execute(
                    """
                    INSERT INTO opponent_team_suggestions
                        (user_id, demo_id, clan_name, steamids, player_names, map, dismissed, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, 0, NOW(), NOW())
                    ON DUPLICATE KEY UPDATE
                        demo_id      = VALUES(demo_id),
                        steamids     = VALUES(steamids),
                        player_names = VALUES(player_names),
                        map          = VALUES(map),
                        dismissed    = 0,
                        updated_at   = NOW()
                    """,
                    (user_id, demo_id, clan_name, steamids_json, names_json, map_name),
                )
            except Exception as e:
                logger.warning(f"[AntiStrat] Could not upsert suggestion for '{clan_name}': {e}")
        await conn.commit()

    logger.info(f"[AntiStrat] Stored suggestion for unmatched team '{clan_name}'")


async def auto_link_demo_to_opponent(
    pool: aiomysql.Pool,
    demo_id: int,
    opponent_team_id: int,
    players: list[dict],
) -> None:
    """
    Link a demo to an opponent profile and upsert player records.
    """
    async with pool.acquire() as conn:
        async with conn.cursor() as cursor:
            # Link demo
            await cursor.execute(
                """
                INSERT IGNORE INTO opponent_team_demos (opponent_team_id, demo_id, created_at, updated_at)
                VALUES (%s, %s, NOW(), NOW())
                """,
                (opponent_team_id, demo_id),
            )

            # Upsert players
            for player in players:
                steamid = str(player.get("steamid", ""))
                name    = player.get("name", "Unknown")
                if not steamid or steamid == "0":
                    continue

                await cursor.execute(
                    """
                    INSERT INTO opponent_team_players (opponent_team_id, steamid, name, created_at, updated_at)
                    VALUES (%s, %s, %s, NOW(), NOW())
                    ON DUPLICATE KEY UPDATE name = VALUES(name), updated_at = NOW()
                    """,
                    (opponent_team_id, steamid, name),
                )

        await conn.commit()

    logger.info(f"Demo {demo_id} auto-linked to opponent {opponent_team_id} with {len(players)} players")


# ─── AI pattern summary ───────────────────────────────────────────────────────

async def generate_demo_ai_summary(
    patterns: TeamPatterns,
    kda_stats: list[dict],
) -> dict:
    """
    Call Odin (OpenAI-compatible) to generate a natural language tactical summary
    for a single team from a single demo.

    Returns a structured dict that can be stored in demo_stats or used in the UI.
    """
    if not ODIN_API_KEY:
        logger.warning("ODIN_API_KEY not set, skipping AI demo summary")
        return {}

    payload = {
        "clan_name":          patterns.clan_name,
        "map":                patterns.map,
        "rounds_analyzed":    patterns.rounds_analyzed,
        "fast_rush_rate":     patterns.fast_rush_rate,
        "eco_aggression_rate": patterns.eco_aggression_rate,
        "round_patterns": [
            {
                "round":      p.round_num,
                "pattern":    p.pattern,
                "confidence": p.confidence,
            }
            for p in patterns.round_patterns
        ],
        "player_kda": [
            {
                "steamid": s.get("steamid"),
                "name":    s.get("name"),
                "kills":   s.get("kills"),
                "deaths":  s.get("deaths"),
                "rating":  s.get("rating"),
            }
            for s in kda_stats
        ],
    }

    system_msg = (
        "You are a professional CS2 coach. Analyse the provided match data for a single team "
        "and return a short JSON scouting report. Be tactical and specific."
    )

    user_msg = f"""
Team "{patterns.clan_name}" on {patterns.map}.

Match data:
{json.dumps(payload, indent=2)}

Return JSON:
{{
  "summary": "2-3 sentence tactical summary",
  "playstyle": "passive|default|aggressive",
  "key_threats": ["..."],
  "exploitable_patterns": ["..."],
  "eco_behavior": "description of how they play eco rounds"
}}
"""

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{ODIN_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {ODIN_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model":       ODIN_MODEL,
                    "temperature": 0.2,
                    "messages": [
                        {"role": "system", "content": system_msg},
                        {"role": "user",   "content": user_msg},
                    ],
                    "response_format": {"type": "json_object"},
                },
                timeout=aiohttp.ClientTimeout(total=45),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(f"Odin API error {resp.status}: {body}")
                    return {}

                data    = await resp.json()
                content = data["choices"][0]["message"]["content"]
                return json.loads(content)

    except Exception as exc:
        logger.error(f"AI summary generation failed: {exc}")
        return {}


# ─── Main entry point (called from demo_processor.py) ────────────────────────

async def run_antistrat_analysis(
    pool: aiomysql.Pool,
    demo_id: int,
    user_id: int,
    frame_df,
    kills_df,
    rounds_meta: list[dict],
    stats_json_list: list[dict],
) -> None:
    """
    Full antistrat post-processing pipeline for a freshly parsed demo.

    Steps:
      1. Detect rule-based round patterns for both teams
      2. Find the user's team_ids from the DB
      3. Try to auto-match each parsed team to an existing OpponentTeam
      4. If match found, link demo + upsert players
      5. Generate an AI summary for the opponent team (async, non-blocking)
      6. Store demo-level AI summary in demo_stats (ai_summary column, if present)
    """
    try:
        logger.info(f"[AntiStrat] Starting analysis for demo {demo_id}")

        team_a, team_b = detect_round_patterns(frame_df, kills_df, rounds_meta)

        # Fetch the user's team memberships
        async with pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute(
                    "SELECT team_id FROM team_members WHERE user_id = %s",
                    (user_id,),
                )
                rows     = await cursor.fetchall()
                team_ids = [r["team_id"] for r in rows]

        if not team_ids:
            logger.info(f"[AntiStrat] User {user_id} has no teams — matching against owned profiles only")

        # Always try to match BOTH teams against opponent profiles.
        # A demo contains two teams — either could be a tracked opponent.
        kda_by_id = {str(s.get("steamid", "")): s for s in stats_json_list if s.get("side") == "all"}

        matched_any = False

        for team_patterns in (team_a, team_b):
            opp_id = await find_opponent_match(
                pool,
                user_id,
                team_ids,
                team_patterns.clan_name,
                team_patterns.steamids,
            )

            if not opp_id:
                logger.info(f"[AntiStrat] No match for '{team_patterns.clan_name}'")
                continue

            players = [
                {"steamid": sid, "name": kda_by_id.get(sid, {}).get("name", "Unknown")}
                for sid in team_patterns.steamids
            ]

            await auto_link_demo_to_opponent(pool, demo_id, opp_id, players)
            matched_any = True

            # AI summary for this team
            opp_kda = [
                s for s in stats_json_list
                if s.get("side") == "all" and str(s.get("steamid", "")) in set(team_patterns.steamids)
            ]
            summary = await generate_demo_ai_summary(team_patterns, opp_kda)

            if summary:
                async with pool.acquire() as conn:
                    async with conn.cursor() as cursor:
                        try:
                            await cursor.execute(
                                "UPDATE demo_stats SET ai_antistrat_summary = %s WHERE demo_id = %s",
                                (json.dumps(summary), demo_id),
                            )
                            await conn.commit()
                        except Exception:
                            pass  # Column may not exist yet; non-fatal

            logger.info(f"[AntiStrat] Demo {demo_id} linked to opponent {opp_id} ('{team_patterns.clan_name}')")

        # For each unmatched team, store a suggestion so the user can create a profile
        for team_patterns in (team_a, team_b):
            # Skip if already matched above
            if matched_any:
                # Check if THIS specific team was matched
                opp_id_check = await find_opponent_match(
                    pool, user_id, team_ids,
                    team_patterns.clan_name, team_patterns.steamids,
                )
                if opp_id_check:
                    continue

            if not team_patterns.clan_name or team_patterns.clan_name.strip() in ("", "unconnected"):
                continue

            player_names = [
                kda_by_id.get(sid, {}).get("name", "Unknown")
                for sid in team_patterns.steamids
            ]

            # Fetch map name from demo
            map_name = ""
            try:
                async with pool.acquire() as conn:
                    async with conn.cursor(aiomysql.DictCursor) as cursor:
                        await cursor.execute("SELECT map FROM demos WHERE id = %s", (demo_id,))
                        row = await cursor.fetchone()
                        map_name = row["map"] if row else ""
            except Exception:
                pass

            await upsert_suggestion(
                pool, user_id, demo_id,
                team_patterns.clan_name,
                team_patterns.steamids,
                player_names,
                map_name,
            )

        if not matched_any:
            logger.info(
                f"[AntiStrat] No opponent match for either team "
                f"('{team_a.clan_name}' / '{team_b.clan_name}') — suggestions stored"
            )

    except Exception as exc:
        logger.error(f"[AntiStrat] Analysis failed for demo {demo_id}: {exc}")