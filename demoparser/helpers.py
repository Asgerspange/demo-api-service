from collections import defaultdict
import json
import pandas as pd

def get_total_kda_dict(kills):
    total_KDA = []
    
    # Convert the DataFrame to records (list of dictionaries) first
    kills_records = kills.to_dict('records')
    
    # Now process using dictionaries instead of DataFrame operations
    unique_steamids = set(kill["attacker_steamid"] for kill in kills_records if not pd.isna(kill["attacker_steamid"]))
    
    for steamid in unique_steamids:
        # Find name for this steamid
        name = next((kill["attacker_name"] for kill in kills_records 
                     if kill["attacker_steamid"] == steamid and not pd.isna(kill["attacker_name"])), None)
        
        if not name:
            continue
            
        for side in ["t", "ct", "all"]:
            # Count kills, deaths, assists
            if side == "all":
                kills_count = sum(1 for kill in kills_records if kill["attacker_steamid"] == steamid)
                deaths_count = sum(1 for kill in kills_records if kill["victim_steamid"] == steamid)
                assists_count = sum(1 for kill in kills_records if kill["assister_steamid"] == steamid)
            else:
                kills_count = sum(1 for kill in kills_records 
                                if kill["attacker_steamid"] == steamid and kill["attacker_side"] == side)
                deaths_count = sum(1 for kill in kills_records 
                                 if kill["victim_steamid"] == steamid and kill["victim_side"] == side)
                assists_count = sum(1 for kill in kills_records 
                                  if kill["assister_steamid"] == steamid and kill["assister_side"] == side)
            
            total_KDA.append({
                "name": name,
                "steamid": steamid,
                "side": side,
                "kills": kills_count,
                "deaths": deaths_count,
                "assists": assists_count
            })
    
    return total_KDA

def get_hitgroup_dict(kills):
    result = []
    kills["attacker_steamid"] = kills["attacker_steamid"].astype(str)

    grouped = kills.groupby(["attacker_steamid", "attacker_side", "hitgroup"]).size().unstack(fill_value=0)

    for steamid in kills["attacker_steamid"].unique():
        if steamid == "None" or pd.isna(steamid):
            continue
        
        filtered_kills = kills[kills["attacker_steamid"] == steamid]
        if filtered_kills.empty:
            continue

        name = filtered_kills["attacker_name"].iloc[0]
        for side in ["t", "ct", "all"]:
            if side == "all":
                hit_counts = grouped.loc[steamid].sum() if steamid in grouped.index else {}
            else:
                hit_counts = grouped.xs((steamid, side), level=["attacker_steamid", "attacker_side"], drop_level=False).sum() if (steamid, side) in grouped.index else {}

            result.append({
                "name": name,
                "steamid": steamid,
                "side": side,
                "headshots": int(hit_counts.get("head", 0) + hit_counts.get("neck", 0)),
                "chest": int(hit_counts.get("chest", 0)),
                "stomach": int(hit_counts.get("stomach", 0)),
                "left_arm": int(hit_counts.get("left_arm", 0)),
                "right_arm": int(hit_counts.get("right_arm", 0)),
                "left_leg": int(hit_counts.get("left_leg", 0)),
                "right_leg": int(hit_counts.get("right_leg", 0)),
                "generic": int(hit_counts.get("generic", 0))
            })

    return result

def parse_bomb_events(pickups, drops, plants, last_round_tick):
    tickdict = {}

    for drop in drops.to_dict(orient="records"):
        # Find the next closest pickup tick, default to last_round_tick
        closest_pickup = pickups.loc[pickups["tick"] > drop["tick"]]
        if not closest_pickup.empty:
            closest_pickup = closest_pickup.iloc[0]
        else:
            closest_pickup = None

        next_tick = (
            closest_pickup["tick"]
            if closest_pickup is not None and not closest_pickup.empty
            else last_round_tick
        )

        max_ticks = min(next_tick - drop["tick"], 64)

        # Set closest_pickup to drop if there are no pickups, this is not totally accurate but it's better than nothing
        if closest_pickup is None or closest_pickup.empty:
            closest_pickup = drop

        for tick in range(drop["tick"], drop["tick"] + max_ticks):
            t = (tick - drop["tick"]) / max_ticks
            # Safely handle None values for coordinates
            drop_X = drop["user_X"] if drop["user_X"] is not None else 0.0
            drop_Y = drop["user_Y"] if drop["user_Y"] is not None else 0.0
            drop_Z = drop["user_Z"] if drop["user_Z"] is not None else 0.0
            pickup_X = closest_pickup["user_X"] if closest_pickup["user_X"] is not None else 0.0
            pickup_Y = closest_pickup["user_Y"] if closest_pickup["user_Y"] is not None else 0.0
            pickup_Z = closest_pickup["user_Z"] if closest_pickup["user_Z"] is not None else 0.0

            tickdict[tick] = {
                "X": float(
                    drop_X + t * (pickup_X - drop_X)
                ),
                "Y": float(
                    drop_Y + t * (pickup_Y - drop_Y)
                ),
                "Z": float(
                    drop_Z + t * (pickup_Z - drop_Z)
                ),
                "planted_ticks": None,
            }

        for tick in range(drop["tick"] + max_ticks, next_tick):
            tickdict[tick] = {
                "X": float(closest_pickup["user_X"]) if closest_pickup["user_X"] is not None else 0.0,
                "Y": float(closest_pickup["user_Y"]) if closest_pickup["user_Y"] is not None else 0.0,
                "Z": float(closest_pickup["user_Z"]) if closest_pickup["user_Z"] is not None else 0.0,
                "planted_ticks": None,
            }

    plants = plants.to_dict(orient="records")
    if len(plants) == 0:
        return tickdict

    plant = plants[0]
    max_tick = min(last_round_tick, 64 * 40 + plant["tick"])
    for tick in range(plant["tick"], max_tick):
        tickdict[tick] = {
            "X": float(plant["user_X"]),
            "Y": float(plant["user_Y"]),
            "Z": float(plant["user_Z"]),
            "planted_ticks": tick - plant["tick"],
        }

    return tickdict

def polars_to_pandas_safe(polars_df):
    """
    Ultra-simple version that just preserves SteamIDs as exact string representations.
    """
    import polars as pl
    import pandas as pd
    
    # Make a copy of the DataFrame
    df_copy = polars_df.clone()
    
    # Convert large integer columns to strings in Polars
    for col in df_copy.columns:
        col_type = df_copy.schema[col]
        if str(col_type) in ['UInt64', 'u64', 'Int64', 'i64']:
            # Explicitly format large integers as full strings without scientific notation
            df_copy = df_copy.with_columns(pl.col(col).cast(pl.Utf8))
    
    # Convert to pandas without any further processing
    pandas_df = df_copy.to_pandas()
    
    return pandas_df
def create_heatmap_dict(kills):
    heatmap_kill_dict = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    heatmap_death_dict = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    
    if "attacker_steamid" in kills.columns:
        kills["attacker_steamid"] = kills["attacker_steamid"].astype(str)
    
    if "victim_steamid" in kills.columns:
        kills["victim_steamid"] = kills["victim_steamid"].astype(str)

    for record in kills.to_dict(orient="records"):
        # Skip records with missing or identical Steam IDs
        if not record["attacker_steamid"] or not record["victim_steamid"] or pd.isna(record["attacker_steamid"]) or pd.isna(record["victim_steamid"]):
            continue
        if record["attacker_steamid"] == "None" or record["victim_steamid"] == "None":
            continue
        if record["attacker_steamid"] == record["victim_steamid"]:
            continue
        
        # Use strings directly instead of converting to int
        heatmap_kill_dict[record["attacker_steamid"]][record["round_num"]][(record["attacker_X"], record["attacker_Y"])] += 1
        heatmap_death_dict[record["victim_steamid"]][record["round_num"]][(record["victim_X"], record["victim_Y"])] += 1

    heatmap_dict = {
        "kills": json.dumps(
                {str(id): {round: [{"x": coords[0], "y": coords[1], "value": value} for coords, value in round_data.items() ] for round, round_data in id_data.items()} for id, id_data in heatmap_kill_dict.items()}
            ),
        "deaths": json.dumps(
                {str(id): {round: [{"x": coords[0], "y": coords[1], "value": value} for coords, value in round_data.items() ] for round, round_data in id_data.items()} for id, id_data in heatmap_death_dict.items()}
            )
        }

    return heatmap_dict
        
_TICK_FIELDS = frozenset({
    "tick", "X", "Y", "Z",
    "active_weapon_name", "armor_value", "armor", "balance", "health",
    "inventory", "name", "steamid", "team_clan_name", "side", "yaw",
    "kills_total", "deaths_total", "assists_total", "pitch",
})

def create_tick_dict(round_data, columns=None):
    # Narrow to only the fields we need before calling to_dict (much less work in C)
    keep = [c for c in round_data.columns if c in _TICK_FIELDS]
    df = round_data[keep].copy()

    # Coalesce armor/armor_value → armor_value (both column names exist in some awpy versions)
    if "armor" in df.columns:
        if "armor_value" in df.columns:
            df["armor_value"] = df["armor_value"].where(
                df["armor_value"].notna() & (df["armor_value"] != 0), df["armor"]
            )
            df.drop(columns=["armor"], inplace=True)
        else:
            df.rename(columns={"armor": "armor_value"}, inplace=True)

    if "side" in df.columns:
        df.rename(columns={"side": "team_name"}, inplace=True)

    # Vectorised coordinate rounding + NaN fill (C-level, no Python loop needed)
    for col in ("X", "Y", "Z"):
        if col in df.columns:
            df[col] = df[col].round(1).fillna(0)

    str_cols  = [c for c in ("active_weapon_name", "name", "steamid", "team_clan_name", "team_name") if c in df.columns]
    num_cols  = [c for c in ("balance", "health", "armor_value", "yaw", "kills_total", "deaths_total", "assists_total", "pitch") if c in df.columns]
    if str_cols:
        df[str_cols] = df[str_cols].fillna("")
    if num_cols:
        df[num_cols] = df[num_cols].fillna(0)

    # Single to_dict call (C-level); Python loop only does pop+append (~2 ops/row vs ~17 before)
    records = df.to_dict(orient="records")
    tick_dict = defaultdict(lambda: {"players": [], "weapon_fires": [], "bomb": None, "grenades": []})
    for record in records:
        tick_dict[record.pop("tick")]["players"].append(record)
    return tick_dict

def create_filtered_kill_tick_dict(round_data):
    # Fields to keep
    fields_to_keep = [
        "tick", "headshot", "thrusmoke", "victim_name", "victim_side", 
        "assistedflash", "attacker_side", "attackerblind", "attackerinair", 
        "victim_steamid", "assister_steamid", "attacker_steamid", 
        "attacker_name", "assister_name", "noscope", "weapon"
    ]
    
    data_records = round_data.to_dict(orient="records")
    tick_dict = defaultdict(list)

    for record in data_records:
        # Filter to only keep desired fields
        filtered_record = {field: record.get(field) for field in fields_to_keep if field in record}
        tick_dict[record["tick"]].append(filtered_record)

    # Sort by tick (lowest to highest)
    sorted_tick_dict = dict(sorted(tick_dict.items()))
    
    return sorted_tick_dict
def create_kill_tick_dict(round_data):
    data_records = round_data.to_dict(orient="records")
    tick_dict = defaultdict(list)

    for record in data_records:
        tick_dict[record["tick"]].append(record)

    return tick_dict

import numpy as np

def create_stats_dict(stats, frame_df, rounds):
    stats_dict = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    stats_records = stats.to_dict(orient="records")
    
    # Process all stats records first to build the base structure
    for stat in stats_records:
        name = stat['name']
        side = stat['side']
        n_rounds = stat['n_rounds']
        dmg = stat['dmg']
        adr = stat['adr']
        steamid = stat['steamid']

        stats_dict[name][side]['n_rounds'] = n_rounds
        stats_dict[name][side]['dmg'] = dmg
        stats_dict[name][side]['adr'] = adr
        stats_dict[name][side]['steamid'] = steamid
        stats_dict[name][side]['name'] = name
        stats_dict[name][side]['side'] = side

    # Map steamid to player name for easier lookup
    steamid_to_name = {stat['steamid']: stat['name'] for stat in stats_records}
    
    # Add various stats from frame_df
    for steamid, name in steamid_to_name.items():
        player_frames = frame_df[frame_df['steamid'] == steamid]
        print(f"Processing frames for player: {name} with steamid: {steamid} with rank: {player_frames['rank'].iloc[0] if not player_frames.empty else 'N/A'}")

        if not player_frames.empty:
            if int(player_frames["rank"].iloc[0]) > 18:
                rank_value = player_frames["rank"].iloc[0]
                rank_int = int(rank_value)
                stats_dict[name]["all"]['rank'] = rank_int
                stats_dict[name]["all"]['rank_type'] = "premier"
            elif int(player_frames["rank"].iloc[0]) <= 18:
                rank_value = player_frames["rank"].iloc[0]
                rank_int = int(rank_value)
                stats_dict[name]["all"]['rank'] = rank_int
                stats_dict[name]["all"]['rank_type'] = "mm"

            stats_dict[name]["all"]['5k_rounds'] = int(player_frames['ace_rounds_total'].max())
            stats_dict[name]["all"]['4k_rounds'] = int(player_frames['4k_rounds_total'].max())
            stats_dict[name]["all"]['3k_rounds'] = int(player_frames['3k_rounds_total'].max())
            stats_dict[name]["all"]['utility_damage'] = int(player_frames['utility_damage_total'].max())
            stats_dict[name]["all"]['enemies_flashed'] = int(player_frames['enemies_flashed_total'].max())
            stats_dict[name]["all"]['mvps'] = int(player_frames['mvps'].max())
            stats_dict[name]["all"]['headshot_kills'] = int(player_frames['headshot_kills_total'].max())
            
            # Initialize clutch win counters
            stats_dict[name]["all"]['1v1'] = 0
            stats_dict[name]["all"]['1v2'] = 0
            stats_dict[name]["all"]['1v3'] = 0
            stats_dict[name]["all"]['1v4'] = 0
            stats_dict[name]["all"]['1v5'] = 0
            
            # Also initialize for each side
            sides = set(player_frames['side'].unique())
            for side in sides:
                if side:  # Skip empty side values
                    stats_dict[name][side]['1v1'] = 0
                    stats_dict[name][side]['1v2'] = 0
                    stats_dict[name][side]['1v3'] = 0
                    stats_dict[name][side]['1v4'] = 0
                    stats_dict[name][side]['1v5'] = 0

    # Process clutch win statistics
    for _, round_data in rounds.iterrows():
        round_num = round_data['round_num']
        winner_side = round_data['winner']  # 't' or 'ct'
        round_end_tick = round_data['end']
        
        # Get frame data at the end of the round
        # We'll use the frames that are closest to the end of the round
        end_frames = frame_df[frame_df['round_num'] == round_num].copy()
        
        if end_frames.empty:
            continue
            
        # Find frames with the highest tick that's <= round_end_tick
        valid_frames = end_frames[end_frames['tick'] <= round_end_tick]
        if valid_frames.empty:
            continue
            
        max_tick = valid_frames['tick'].max()
        last_frame = valid_frames[valid_frames['tick'] == max_tick]
        
        # Count players alive on each side
        t_frames = last_frame[last_frame['side'] == 't']
        ct_frames = last_frame[last_frame['side'] == 'ct']
        
        t_alive_count = len(t_frames[t_frames['health'] > 0])
        ct_alive_count = len(ct_frames[ct_frames['health'] > 0])
        
        # Check for clutch situation (only one player alive on the winning side)
        if (winner_side == 't' and t_alive_count == 1) or (winner_side == 'ct' and ct_alive_count == 1):
            # Identify the player who clutched
            if winner_side == 't':
                clutch_players = t_frames[t_frames['health'] > 0]
                enemies_alive = ct_alive_count
            else:
                clutch_players = ct_frames[ct_frames['health'] > 0]
                enemies_alive = t_alive_count
            
            if not clutch_players.empty and 1 <= enemies_alive <= 5:
                for _, clutch_player in clutch_players.iterrows():
                    player_name = clutch_player['name']
                    player_side = clutch_player['side']
                    player_steamid = clutch_player['steamid']
                    
                    # Add to the appropriate 1vX statistic
                    clutch_key = f'1v{enemies_alive}'
                    
                    # Make sure player exists in stats_dict
                    if player_name not in stats_dict or player_side not in stats_dict[player_name]:
                        # If player is not in stats_records but appears in frame_df, add them
                        if player_steamid not in steamid_to_name:
                            continue
                    
                    # Increment clutch count for specific side
                    stats_dict[player_name][player_side][clutch_key] += 1
                    
                    # Also increment in the 'all' aggregation
                    stats_dict[player_name]['all'][clutch_key] += 1
    
    # Convert the nested defaultdict to a list of records format
    records = []
    for name, sides in stats_dict.items():
        for side, stats in sides.items():
            # Ensure all NumPy types are converted to Python native types
            record = {}
            for k, v in stats.items():
                if isinstance(v, np.integer):
                    record[k] = int(v)
                elif isinstance(v, np.floating):
                    record[k] = float(v)
                elif isinstance(v, np.ndarray):
                    record[k] = v.tolist()
                else:
                    record[k] = v
            records.append(record)
    
    # Convert to JSON
    stats_json = json.dumps(records, indent=4)

    return stats_json

def get_kills_for_player(steamid, kills, round_num=None):
    """
    Get kills for a specific player.
    """
    kills = kills[kills["attacker_steamid"] == steamid]
    
    if round_num is not None:
        kills = kills[kills["round_num"] == round_num]
    
    # Convert to a list of dictionaries
    return kills.to_dict(orient="records")