"""Core demo processing functionality."""
import math
import asyncio
import aiomysql
import json
import os
import gzip
import numpy as np
import pandas as pd
import requests
from awpy import Demo
from awpy.stats import adr, kast, rating
from typing import Optional
from loguru import logger
from tempfile import NamedTemporaryFile 
import zstandard as zstd
import shutil
import orjson

_ORJSON_OPT = orjson.OPT_NON_STR_KEYS | orjson.OPT_SERIALIZE_NUMPY

async def _run_post_processing_safe(
    pool, demo_id, user_id, map_name, frame_df, kills_df, rounds_df, stats_json,
    smokes_df=None, infernos_df=None, grenades_df=None, shots_df=None, planted_df=None,
):
    try:
        from post_processor import run_post_processing
        stats_list = json.loads(stats_json) if isinstance(stats_json, str) else stats_json
        await run_post_processing(
            pool            = pool,
            demo_id         = demo_id,
            user_id         = user_id,
            map_name        = map_name,
            frame_df        = frame_df,
            kills_df        = kills_df,
            rounds_df       = rounds_df,
            stats_json_list = stats_list,
            smokes_df       = smokes_df,
            infernos_df     = infernos_df,
            grenades_df     = grenades_df,
            shots_df        = shots_df,
            planted_df      = planted_df,
        )
    except Exception as exc:
        from loguru import logger
        logger.error(f"Post-processing failed for demo {demo_id}: {exc}")


def _orjson_default(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Unserializable type: {type(obj)}")

def _dumps(obj) -> bytes:
    return orjson.dumps(obj, default=_orjson_default, option=_ORJSON_OPT)

from config import SteamConfig
from helpers import (
    get_total_kda_dict, get_hitgroup_dict, create_tick_dict, create_kill_tick_dict,
    parse_bomb_events, create_heatmap_dict, polars_to_pandas_safe, create_stats_dict,
    get_kills_for_player, create_filtered_kill_tick_dict
)

class DemoProcessor:
    """Handles processing of CS:GO demo files."""
    
    def __init__(self, steam_config: SteamConfig):
        self.steam_config = steam_config

    def json_serializer(self, obj):
        """Serialize obj to a JSON string safe for MySQL JSON columns."""
        return _dumps(obj).decode()

    async def process_demo_from_file(
        self, 
        file_path: str, 
        pool: aiomysql.Pool, 
        user_id: int, 
        name: str,
        save: bool = False,
        version: int = 1
    ) -> int:
        """Process a demo file directly from a file path."""
        logger.info(f"Processing demo from file: {file_path}")
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Demo file not found: {file_path}")
        
        logger.info("Parsing demo")
        _player_props = [
            "balance", "active_weapon_name", "is_in_reload", "is_walking", "pitch",
            "armor_value", "flash_duration", "has_defuser", "has_helmet",
            "inventory", "team_clan_name", "yaw", "kills_total", "deaths_total",
            "assists_total", "enemies_flashed_total", "equipment_value_total",
            "utility_damage_total", "ace_rounds_total", "4k_rounds_total",
            "3k_rounds_total", "damage_total", "crosshair_code", "leader_honors",
            "teacher_honors", "friendly_honors", "headshot_kills_total", "ping",
            "mvps", "rank", "rank_if_win", "rank_if_loss", "rank_if_tie", "comp_rank_type"
        ]

        def _do_parse():
            d = Demo(path=file_path, verbose=True)
            d.parse(player_props=_player_props)
            return d

        dem = await asyncio.to_thread(_do_parse)
        logger.info("Demo parsed successfully")
        demo_id = None

        if save:
            async with pool.acquire() as db:
                sql = "INSERT INTO demos (name, owner, map, hide, version) VALUES (%s, %s, %s, %s, %s)"
                val = (name, user_id, dem.header["map_name"], 1, version)
                async with db.cursor() as cursor:
                    await cursor.execute(sql, val)
                    demo_id = cursor.lastrowid
                    await db.commit()
                    logger.info(f"Demo {demo_id} created")
        
        await self._process_demo_data(dem, pool, demo_id, user_id, save)
        
        return demo_id
    
    async def process_demo_from_chunks(
        self,
        queued_demo_id: int,
        pool,
        user_id: int,
        name: str,
        version: int = 2,
        metadata: Optional[str] = None,
    ) -> int:
        meta_dict = {}
        if metadata:
            try:
                meta_dict = json.loads(metadata) if isinstance(metadata, str) else metadata
            except Exception as e:
                logger.error(f"Failed to parse metadata: {e}")

        source = meta_dict.get('source')
        temp_file_path = None

        try:
            if not source:
                async with pool.acquire() as conn:
                    async with conn.cursor() as cursor:
                        await cursor.execute(
                            "SELECT data FROM queued_demo_chunks WHERE queued_demo_id = %s ORDER BY chunk_index ASC",
                            (queued_demo_id,),
                        )
                        demo_chunks = await cursor.fetchall()
                
                if not demo_chunks:
                    raise ValueError(f"No chunks found for queued_demo_id {queued_demo_id}")

                with NamedTemporaryFile("wb", delete=False, suffix=".dem.gz") as fp:
                    logger.info(f"Combining {len(demo_chunks)} chunks for {name}")
                    for chunk in demo_chunks:
                        fp.write(chunk[0])
                    temp_file_path = fp.name

            else:
                demo_url = meta_dict.get('demo_url')
                if not demo_url:
                    raise ValueError("Source is set but no demo_url provided in metadata")

                with NamedTemporaryFile("wb", delete=False, suffix=".dem") as fp:
                    logger.info(f"Downloading and decompressing {source} demo from: {demo_url}")
                    
                    with requests.get(demo_url, stream=True, timeout=60) as r:
                        r.raise_for_status()
                        dctx = zstd.ZstdDecompressor()
                        try:
                            with dctx.stream_reader(r.raw) as reader:
                                shutil.copyfileobj(reader, fp)
                        except Exception as e:
                            logger.error(f"Decompression failed: {e}")
                            raise

                    temp_file_path = fp.name

            demo_id = await self.process_demo_from_file(
                temp_file_path, pool, user_id, name, True, version
            )

            if not source:
                logger.info("Cleaning up database chunks")
                await self.cleanup_chunks(queued_demo_id, pool)
            
            return demo_id
                
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)
                logger.debug(f"Deleted temp file: {temp_file_path}")
        
    async def cleanup_chunks(self, queued_demo_id: int, pool: aiomysql.Pool) -> None:
        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "DELETE FROM queued_demo_chunks WHERE queued_demo_id = %s",
                    (queued_demo_id,),
                )
            await conn.commit()

    async def _process_demo_data(self, dem: Demo, pool: aiomysql.Pool, demo_id: int, user_id: int, save: bool = True):
        """Process demo data and insert into database."""
        import polars as pl

        def _calc_kast():
            return polars_to_pandas_safe(kast(dem)).replace({float("nan"): None})

        def _calc_rating():
            return polars_to_pandas_safe(rating(dem)).replace({float("nan"): None})

        def _calc_adr():
            return polars_to_pandas_safe(adr(dem)).replace({float("nan"): None})

        def _convert_ticks():
            return polars_to_pandas_safe(dem.ticks).replace({float("nan"): None})

        def _process_grenades_polars():
            return (
                dem.grenades.lazy()
                .drop_nulls(subset=["X", "Y", "Z"])
                .with_columns([pl.col("grenade_type").str.to_lowercase().alias("grenade_type")])
                .with_columns([
                    pl.when(pl.col("grenade_type").str.contains("molotov")).then(pl.lit("molotov"))
                    .when(pl.col("grenade_type").str.contains("hegrenade")).then(pl.lit("he_grenade"))
                    .when(pl.col("grenade_type").str.contains("smoke")).then(pl.lit("smoke"))
                    .when(pl.col("grenade_type").str.contains("flashbang")).then(pl.lit("flashbang"))
                    .when(pl.col("grenade_type").str.contains("decoy")).then(pl.lit("decoy_grenade"))
                    .otherwise(pl.col("grenade_type"))
                    .alias("grenade_type")
                ])
                .collect()
            )

        kast_df    = await asyncio.to_thread(_calc_kast)
        rating_df  = await asyncio.to_thread(_calc_rating)
        adr_df     = await asyncio.to_thread(_calc_adr)

        frame_df, grenades_polars = await asyncio.gather(
            asyncio.to_thread(_convert_ticks),
            asyncio.to_thread(_process_grenades_polars),
        )

        kast_json   = kast_df.to_json(orient="records")
        rating_json = rating_df.to_json(orient="records")

        pd.set_option("display.max_columns", None)

        def _convert_all():
            bomb     = polars_to_pandas_safe(dem.bomb).replace({float("nan"): None})
            shots    = polars_to_pandas_safe(dem.shots).replace({float("nan"): None})
            kills    = polars_to_pandas_safe(dem.kills).replace({float("nan"): None})
            kills["attacker_steamid"] = kills["attacker_steamid"].astype(str)
            smokes   = polars_to_pandas_safe(dem.smokes).replace({float("nan"): None})
            infernos = polars_to_pandas_safe(dem.infernos).replace({float("nan"): None})
            grenades = polars_to_pandas_safe(grenades_polars)
            pickup   = polars_to_pandas_safe(dem.events["bomb_pickup"]).replace({float("nan"): None})
            dropped  = polars_to_pandas_safe(dem.events["bomb_dropped"]).replace({float("nan"): None})
            planted  = polars_to_pandas_safe(dem.events["bomb_planted"]).replace({float("nan"): None})
            rounds   = polars_to_pandas_safe(dem.rounds).replace({float("nan"): None})
            return bomb, shots, kills, smokes, infernos, grenades, pickup, dropped, planted, rounds

        results = await asyncio.to_thread(_convert_all)
        kills_df = results[2]
        dem.bomb, dem.shots, dem.kills, dem.smokes, dem.infernos, dem.grenades = results[:6]
        dem.events["bomb_pickup"], dem.events["bomb_dropped"], dem.events["bomb_planted"] = results[6:9]
        dem.rounds = results[9]

        # Keep references to the converted DFs for post-processing
        smokes_df   = dem.smokes
        infernos_df = dem.infernos
        grenades_df = dem.grenades
        shots_df    = dem.shots
        planted_df  = dem.events["bomb_planted"]

        stats_json = await asyncio.to_thread(create_stats_dict, adr_df, frame_df, dem.rounds)

        heatmap_data   = create_heatmap_dict(dem.kills)
        heatmap_kills  = heatmap_data["kills"]
        heatmap_deaths = heatmap_data["deaths"]

        total_hitgroups      = get_hitgroup_dict(dem.kills)
        total_hitgroups_json = self.json_serializer(total_hitgroups)

        total_KDA      = get_total_kda_dict(dem.kills)
        total_KDA_json = self.json_serializer(total_KDA)

        steam_task = asyncio.create_task(self._get_steam_player_data(frame_df))

        await self._process_rounds(dem, frame_df, pool, demo_id, stats_json, kast_json,
                                   rating_json, total_KDA_json, total_hitgroups_json,
                                   heatmap_kills, heatmap_deaths, save, queued_demo_id=None)

        meta = await steam_task

        if save:
            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    sql = "UPDATE demos SET meta = %s WHERE id = %s"
                    val = (self.json_serializer(meta), demo_id)
                    await cursor.execute(sql, val)
                    await conn.commit()
                logger.info(f"Meta for {demo_id} created")

        if save:
            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    sql = "UPDATE demos SET hide = 0 WHERE id = %s"
                    val = (demo_id,)
                    await cursor.execute(sql, val)
                    await conn.commit()
                logger.info(f"Demo {demo_id} is now visible")

        if save and demo_id:
            asyncio.create_task(
                _run_post_processing_safe(
                    pool        = pool,
                    demo_id     = demo_id,
                    user_id     = user_id,
                    map_name    = dem.header.get("map_name", ""),
                    frame_df    = frame_df,
                    kills_df    = kills_df,
                    rounds_df   = dem.rounds,
                    stats_json  = stats_json,
                    smokes_df   = smokes_df,
                    infernos_df = infernos_df,
                    grenades_df = grenades_df,
                    shots_df    = shots_df,
                    planted_df  = planted_df,
                )
            )
    
    async def _get_steam_player_data(self, frame_df: pd.DataFrame) -> dict:
        """Get Steam player data from API."""
        meta = {}
        steamIds = frame_df["steamid"].unique()
        steam_ids_str = ",".join([str(steamId) for steamId in steamIds])
        url = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/"
        params = {
            'key': self.steam_config.api_key,
            'steamids': steam_ids_str
        }

        try:
            response = await asyncio.to_thread(requests.get, url, params=params, timeout=10, verify=False)
            response.raise_for_status()
            data = response.json()
            meta["steamPlayers"] = data.get('response', {}).get('players', [])
        except requests.exceptions.RequestException as e:
            logger.error(f"Steam API error: {e}")
            meta["steamPlayers"] = []
        
        return meta
    
    async def _process_rounds(self, dem: Demo, frame_df: pd.DataFrame, pool: aiomysql.Pool,
                          demo_id: int, stats_json: str, kast_json: str, rating_json: str,
                          total_KDA_json: str, total_hitgroups_json: str,
                          heatmap_kills: str, heatmap_deaths: str, save: bool = True, queued_demo_id: int = None):
        """Orchestrate parallel round processing while maintaining full stats/heatmap logic."""
        columns = frame_df.columns
        team_a_score, team_b_score = 0, 0
        round_tick_indices = []
        rounds_to_process = []
        last_round_num = frame_df["round_num"].max()

        rounds_by_num = {r["round_num"]: r for r in dem.rounds.to_dict(orient="records")}

        for round_number, round_data in frame_df.groupby("round_num"):
            r_info = rounds_by_num.get(round_number)
            if r_info is None:
                continue
            
            round_tick_indices.append({
                "round_number": round_number, 
                "tick_start": r_info["start"], 
                "tick_end": r_info["end"]
            })
            
            rounds_to_process.append((round_number, round_data, (team_a_score, team_b_score)))

            ref = round_data.iloc[0]
            curr_side = ref["side"] if ref["side"] else "CT"
            if curr_side[0].upper() == r_info["winner"][0].upper():
                team_a_score += 1
            else:
                team_b_score += 1

            if round_number == last_round_num and save:
                selected_data = round_data[['side', 'name', 'steamid', 'team_clan_name']].drop_duplicates(subset=['steamid'])
                team1 = selected_data.loc[selected_data['side'] == 't']
                team2 = selected_data.loc[selected_data['side'] == 'ct']
                
                team1_json = self.json_serializer(team1.to_dict(orient="records"))
                team2_json = self.json_serializer(team2.to_dict(orient="records"))

                async with pool.acquire() as conn:
                    async with conn.cursor() as cursor:
                        sql_stats = """INSERT INTO demo_stats(demo_id, stats, kast, rating, KDA, hitgroups, team1, team2)
                                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"""
                        await cursor.execute(sql_stats, (
                            demo_id, stats_json, kast_json, rating_json, 
                            total_KDA_json, total_hitgroups_json, team1_json, team2_json
                        ))
                        
                        sql_heat = """INSERT INTO demo_heatmaps(demo_id, kill_data, death_data, team1, team2)
                                     VALUES (%s, %s, %s, %s, %s)"""
                        await cursor.execute(sql_heat, (
                            demo_id, heatmap_kills, heatmap_deaths, team1_json, team2_json
                        ))
                        
                        await conn.commit()
                        logger.info(f"Final stats and heatmaps for demo {demo_id} created")

        for event_type in ["bomb_pickup", "bomb_dropped", "bomb_planted"]:
            for event in dem.events[event_type].itertuples():
                for round_tick in round_tick_indices:
                    if round_tick["tick_start"] <= event.tick <= round_tick["tick_end"]:
                        dem.events[event_type].at[event.Index, "round_num"] = round_tick["round_number"]
                        break

        _empty = pd.DataFrame()
        _rshots    = {rn: g for rn, g in dem.shots.groupby("round_num")}
        _rkills    = {rn: g for rn, g in dem.kills.groupby("round_num")}
        _rgren     = {rn: g for rn, g in dem.grenades.groupby("round_num")}
        _rsmokes   = {rn: g for rn, g in dem.smokes.groupby("round_num")}
        _rinfernos = {rn: g for rn, g in dem.infernos.groupby("round_num")}
        _rpickup   = {rn: g for rn, g in dem.events["bomb_pickup"].groupby("round_num")}
        _rdropped  = {rn: g for rn, g in dem.events["bomb_dropped"].groupby("round_num")}
        _rplanted  = {rn: g for rn, g in dem.events["bomb_planted"].groupby("round_num")}
        _rplayers  = {rn: g[["steamid", "name", "side", "team_clan_name"]].drop_duplicates("steamid")
                      for rn, g in frame_df.groupby("round_num")}

        semaphore = asyncio.Semaphore(15)

        async def worker(r_num, r_df, scores):
            async with semaphore:
                for attempt in range(3):
                    try:
                        await self._process_single_round(
                            rounds_by_num, r_df, r_num, round_tick_indices,
                            pool, demo_id, scores[0], scores[1], save,
                            _rshots.get(r_num, _empty),
                            _rkills.get(r_num, _empty),
                            _rgren.get(r_num, _empty),
                            _rsmokes.get(r_num, _empty),
                            _rinfernos.get(r_num, _empty),
                            _rpickup.get(r_num, _empty),
                            _rdropped.get(r_num, _empty),
                            _rplanted.get(r_num, _empty),
                            _rplayers.get(r_num, _empty),
                        )
                        return
                    except (aiomysql.InternalError, aiomysql.OperationalError) as e:
                        if "Packet sequence" in str(e) and attempt < 2:
                            logger.warning(f"Packet sequence error on round {r_num}, retrying... ({attempt+1}/3)")
                            await asyncio.sleep(0.5 * (attempt + 1))
                            continue
                        logger.error(f"Permanent DB failure on round {r_num}: {e}")
                        raise e

        if rounds_to_process:
            await asyncio.gather(*[worker(rn, rdf, s) for rn, rdf, s in rounds_to_process])
            logger.info(f"Parallel processing of {len(rounds_to_process)} rounds finished.")
        
        logger.info(f"All rounds for demo {demo_id} processed.") 
        if save:
            async with pool.acquire() as conn:
                async with conn.cursor() as cursor:
                    sql = "UPDATE queued_demos SET status = 'completed' WHERE id = %s"
                    val = (queued_demo_id,)
                    await cursor.execute(sql, val)
                    await conn.commit()
                logger.info(f"Demo {queued_demo_id} marked as fully processed")

                async with conn.cursor() as cursor:
                    sql = "UPDATE demos SET hide = 0 WHERE id = %s"
                    val = (demo_id,)
                    await cursor.execute(sql, val)
                    await conn.commit()            


    async def _process_single_round(self, rounds_by_num: dict, round_data: pd.DataFrame, round_number: int,
                                    round_tick_indices: list,
                                    pool: aiomysql.Pool, demo_id: int,
                                    team_a_score: int, team_b_score: int, save: bool = True,
                                    r_shots: pd.DataFrame = None, r_kills: pd.DataFrame = None,
                                    r_grenades: pd.DataFrame = None, r_smokes: pd.DataFrame = None,
                                    r_infernos: pd.DataFrame = None, r_pickup: pd.DataFrame = None,
                                    r_dropped: pd.DataFrame = None, r_planted: pd.DataFrame = None,
                                    r_players: pd.DataFrame = None) -> tuple[int, int]:
        """Process a single round: CPU work inline (asyncio cooperative), DB inserts are async."""
        tick_dict = create_tick_dict(round_data)

        round_info = dict(rounds_by_num[round_number])

        target_tick = round_info["official_end"] - 10
        end_players = (
            tick_dict[target_tick]["players"]
            if target_tick in tick_dict
            else tick_dict[min(tick_dict.keys(), key=lambda t: abs(t - target_tick))]["players"]
        )

        round_info["t_balance"] = sum(
            p["balance"] for p in end_players
            if p.get("team_name", "") and p["team_name"].lower() == "t"
        )
        round_info["ct_balance"] = sum(
            p["balance"] for p in end_players
            if p.get("team_name", "") and p["team_name"].lower() == "ct"
        )

        winning_side = round_info["winner"].lower()
        round_info["winners"] = [p.get("steamid") for p in end_players if p["team_name"] == winning_side]
        round_info["losers"]  = [p.get("steamid") for p in end_players if p["team_name"] != winning_side]

        current_team = (round_data.iloc[0]["side"] or "CT")
        new_a = team_a_score + (1 if current_team[0].upper() == round_info["winner"][0].upper() else 0)
        new_b = team_b_score + (0 if current_team[0].upper() == round_info["winner"][0].upper() else 1)

        round_info["CT_score"] = new_a if current_team.upper() == "CT" else new_b
        round_info["T_score"]  = new_b if current_team.upper() == "CT" else new_a
        logger.info(f"T score: {round_info['T_score']}, CT score: {round_info['CT_score']}")

        round_info["header"] = rounds_by_num[round_number].get("header", {})

        _rk = r_kills if r_kills is not None else pd.DataFrame()
        round_info["alive_players"] = {
            p["steamid"]: {"name": p["name"], "team_name": p["team_name"],
                           "kills": int((_rk["attacker_steamid"] == p["steamid"]).sum())}
            for p in end_players if (p["health"] or 0) > 0
        }
        round_info["dead_players"] = {
            p["steamid"]: {"name": p["name"], "team_name": p["team_name"],
                           "kills": int((_rk["attacker_steamid"] == p["steamid"]).sum())}
            for p in end_players if (p["health"] or 0) <= 0
        }

        kill_dict = create_filtered_kill_tick_dict(_rk)
        for key, value in kill_dict.items():
            if isinstance(value, np.ndarray):
                kill_dict[key] = value.tolist()
        round_info["kills"] = kill_dict

        self._process_weapon_fires(r_shots, tick_dict)
        self._process_bomb_events(r_pickup, r_dropped, r_planted, round_tick_indices, round_number, round_data, tick_dict)
        self._process_grenades(r_grenades, tick_dict)
        smokes, infernos = self._process_smokes_infernos(r_smokes, r_infernos)
        utility = self._create_utilities(r_grenades, r_smokes, r_infernos, r_players, tick_dict)

        record = {
            "ticks": tick_dict,
            "meta": round_info,
            "smokes": smokes,
            "infernos": infernos,
            "kills": create_kill_tick_dict(_rk),
        }

        if save:
            utility_json    = _dumps(utility).decode()
            round_info_json = _dumps(round_info).decode()
            compressed      = gzip.compress(_dumps(record), compresslevel=1)

            async with pool.acquire() as db:
                async with db.cursor() as cursor:
                    await cursor.execute(
                        "INSERT INTO demo_grenades (demo_id, round_index, data) VALUES (%s, %s, %s)",
                        (demo_id, round_number, utility_json),
                    )
                    await cursor.execute(
                        "INSERT INTO demo_rounds (demo_id, round_index, meta, frame_data) VALUES (%s, %s, %s, %s)",
                        (demo_id, round_number, round_info_json, compressed),
                    )
                await db.commit()
            logger.info(f"Demo {demo_id} round {round_number} grenades inserted")
            logger.info(f"Demo {demo_id} round {round_number} inserted")

        return new_a, new_b

    def _process_weapon_fires(self, r_shots: pd.DataFrame, tick_dict: dict):
        """Process weapon fire events for the round using a pre-filtered shots DataFrame."""
        if r_shots is None or r_shots.empty:
            return
        _cols = [c for c in ["tick", "player_name", "player_steamid", "weapon", "player_yaw",
                              "player_X", "player_Y", "round_num"] if c in r_shots.columns]
        for weapon_fire in r_shots[_cols].to_dict(orient="records"):
            name = weapon_fire["weapon"].lower()
            if (
                "grenade" not in name and "knife" not in name and "c4" not in name
                and "bayonet" not in name and "flash" not in name and "molotov" not in name
                and "smoke" not in name and "decoy" not in name
            ):
                tick_dict[weapon_fire["tick"]]["weapon_fires"].append(weapon_fire)

    def _process_bomb_events(self, r_pickup: pd.DataFrame, r_dropped: pd.DataFrame,
                             r_planted: pd.DataFrame, round_tick_indices: list,
                             round_number: int, round_data: pd.DataFrame, tick_dict: dict):
        """Process bomb-related events using pre-filtered event DataFrames."""
        _empty = pd.DataFrame()
        bomb_ticks = parse_bomb_events(
            r_pickup  if r_pickup  is not None else _empty,
            r_dropped if r_dropped is not None else _empty,
            r_planted if r_planted is not None else _empty,
            round_data["tick"].max(),
        )
        for tick, bomb in bomb_ticks.items():
            tick_dict[tick]["bomb"] = bomb

    def _process_grenades(self, r_grenades: pd.DataFrame, tick_dict: dict):
        """Process grenade events using a pre-filtered grenades DataFrame."""
        if r_grenades is None or r_grenades.empty:
            return
        _cols = [c for c in ["thrower_steamid", "thrower", "grenade_type", "tick",
                              "X", "Y", "Z", "entity_id", "round_num"] if c in r_grenades.columns]
        for grenade in r_grenades[_cols].to_dict(orient="records"):
            grenade["thrower_steamid"] = str(grenade["thrower_steamid"])
            tick_dict[grenade["tick"]]["grenades"].append(grenade)

    def _process_smokes_infernos(self, r_smokes: pd.DataFrame, r_infernos: pd.DataFrame) -> tuple:
        """Process smoke and inferno events using pre-filtered DataFrames."""
        _smoke_cols   = ["entity_id", "start_tick", "end_tick", "thrower_name", "thrower_side",
                         "thrower_steamid", "X", "Y", "Z", "round_num"]
        _inferno_cols = _smoke_cols

        def _select(df, cols):
            if df is None or df.empty:
                return []
            return df[[c for c in cols if c in df.columns]].to_dict(orient="records")

        return _select(r_smokes, _smoke_cols), _select(r_infernos, _inferno_cols)

    def _create_utilities(self, r_grenades: pd.DataFrame, r_smokes: pd.DataFrame,
                          r_infernos: pd.DataFrame, r_players: pd.DataFrame,
                          tick_dict: dict) -> dict:
        """Create utility objects for the round using pre-filtered DataFrames."""
        utilities = {}

        if r_grenades is None or r_grenades.empty:
            return utilities

        for entity_id, grenade_data in r_grenades.groupby("entity_id"):
            thrower  = grenade_data["thrower"].iloc[0]
            steamid  = grenade_data["thrower_steamid"].iloc[0]
            gtype    = grenade_data["grenade_type"].iloc[0]
            coords   = grenade_data[["X", "Y", "Z"]].to_numpy(dtype=float)

            def as_list(arr):
                return [float(v) if not (math.isnan(v) or math.isinf(v)) else None for v in arr]

            origin   = as_list(coords[0])
            last_pos = as_list(coords[-1])
            velocities = np.diff(coords, axis=0)

            bounces = []
            for i in range(1, len(velocities)):
                v1 = velocities[i - 1]
                v2 = velocities[i]
                norm1 = np.linalg.norm(v1)
                norm2 = np.linalg.norm(v2)
                if norm1 == 0 or norm2 == 0:
                    continue
                v1n  = v1 / norm1
                v2n  = v2 / norm2
                dot  = np.clip(np.dot(v1n, v2n), -1.0, 1.0)
                angle = np.degrees(np.arccos(dot))
                if angle > 30 or norm2 < norm1 * 0.5:
                    bounces.append(as_list(coords[i]))

            landing = None
            if gtype in ["smoke", "smokegrenade"]:
                sm = r_smokes[r_smokes["entity_id"] == entity_id] if (r_smokes is not None and not r_smokes.empty) else pd.DataFrame()
                landing = as_list([sm["X"].iloc[0], sm["Y"].iloc[0], sm["Z"].iloc[0]]) if not sm.empty else last_pos
            elif gtype in ["molotov", "incendiary"]:
                inf = r_infernos[r_infernos["entity_id"] == entity_id] if (r_infernos is not None and not r_infernos.empty) else pd.DataFrame()
                landing = as_list([inf["X"].iloc[0], inf["Y"].iloc[0], inf["Z"].iloc[0]]) if not inf.empty else last_pos
            else:
                landing = last_pos

            thrower_side = None
            if r_players is not None and not r_players.empty:
                player_row = r_players[r_players["name"] == thrower]
                if not player_row.empty:
                    thrower_side = player_row["side"].iloc[0]
            
            utilities[str(entity_id)] = {
                "thrower":      str(thrower)      if thrower      is not None else None,
                "steamid":      str(steamid)      if steamid      is not None else None,
                "type":         str(gtype)        if gtype        is not None else None,
                "origin":       origin,
                "bounces":      bounces,
                "end":          landing,
                "thrower_side": str(thrower_side) if thrower_side is not None else None,
            }

        return utilities