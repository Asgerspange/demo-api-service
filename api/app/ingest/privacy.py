"""Steam-ID privacy (Stage 13 §13.4).

Steam IDs + names are personal data exposed to every embed. With a per-demo `anonymize` flag we
replace them with **stable per-demo aliases** at payload-build time. Doing it at the *frame*
level (before `build_round_records`) means every downstream structure — player ticks, kills,
grenades/smokes, the round meta's winners/losers/alive/dead — inherits the aliases automatically,
so no real steamid can leak. Aliases are deterministic within a demo (same id → same alias) but
carry no link back to the real account.
"""
from __future__ import annotations

from .rounds import Frames

# columns that hold a steamid / a player name, per frame
_SID_COLS = {
    "ticks": ["steamid"],
    "kills": ["attacker_steamid", "victim_steamid", "assister_steamid"],
    "shots": ["player_steamid"],
    "grenades": ["thrower_steamid"],
    "smokes": ["thrower_steamid"],
    "infernos": ["thrower_steamid"],
}
_NAME_COLS = {
    "ticks": ["name"],
    "kills": ["attacker_name", "victim_name", "assister_name"],
    "shots": ["player_name"],
    "grenades": ["thrower"],
    "smokes": ["thrower_name"],
    "infernos": ["thrower_name"],
}


def build_alias_maps(frames: Frames) -> tuple[dict[str, str], dict[str, str]]:
    """Map each real steamid → opaque alias and each real name → 'Player N' (stable, sorted)."""
    if frames.ticks is None or "steamid" not in frames.ticks.columns:
        return {}, {}
    sids = sorted({str(s) for s in frames.ticks["steamid"].dropna().unique() if str(s)})
    sid_alias = {s: f"anon{i:02d}" for i, s in enumerate(sids, 1)}
    name_alias: dict[str, str] = {}
    for i, s in enumerate(sids, 1):
        mask = frames.ticks["steamid"].astype(str) == s
        for nm in frames.ticks.loc[mask, "name"].dropna().unique():
            name_alias[str(nm)] = f"Player {i}"
    return sid_alias, name_alias


def anonymize_frames(frames: Frames) -> Frames:
    """Replace steamids + names across all frames with stable per-demo aliases."""
    sid_alias, name_alias = build_alias_maps(frames)
    if not sid_alias:
        return frames

    def _remap(df, name):
        if df is None or len(df) == 0:
            return df
        df = df.copy()
        for c in _SID_COLS.get(name, []):
            if c in df.columns:
                df[c] = df[c].astype(str).map(lambda v: sid_alias.get(v, v))
        for c in _NAME_COLS.get(name, []):
            if c in df.columns:
                df[c] = df[c].astype(str).map(lambda v: name_alias.get(v, v))
        return df

    frames.ticks = _remap(frames.ticks, "ticks")
    frames.kills = _remap(frames.kills, "kills")
    frames.shots = _remap(frames.shots, "shots")
    frames.grenades = _remap(frames.grenades, "grenades")
    frames.smokes = _remap(frames.smokes, "smokes")
    frames.infernos = _remap(frames.infernos, "infernos")
    return frames
