"""Header probe — classify a demo *before* the heavy parse (Stage 5.2 step 4 / Stage 11).

Reading just the header is cheap (no tick parse), so we reject unsupported demos before paying
for a full parse: CSGO/source1 and **POV (client-recorded)** demos are rejected here; GOTV
(SourceTV) CS2 demos pass. `classify_header` is a pure function over the header dict so the
classification rules are unit-tested without a real demo.
"""
from __future__ import annotations

from dataclasses import dataclass

from .errors import UnsupportedDemoError

CS2_STAMP = "PBDEMS2"
CSGO_STAMP = "HL2DEMO"
GOTV_CLIENT = "SourceTV Demo"


@dataclass(frozen=True)
class Classification:
    map_name: str
    is_gotv: bool
    demo_type: str           # 'gotv' | 'pov'
    demo_version: str
    tickrate: int | None
    header: dict


def _int_or_none(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def classify_header(header: dict) -> Classification:
    """Classify a parsed demo header; raise UnsupportedDemoError for anything we won't parse.

    CS2 detection is by the source2 file stamp (`PBDEMS2`) / `valve_demo_2` version name; CSGO
    (`HL2DEMO`) is rejected. A GOTV demo has `client_name == 'SourceTV Demo'`; anything else is a
    POV (client-recorded) demo — rejected, since it carries only one player's data + odd entities
    and would render a broken viewer.
    """
    stamp = str(header.get("demo_file_stamp", ""))
    version_name = str(header.get("demo_version_name", ""))

    if stamp.startswith(CSGO_STAMP):
        raise UnsupportedDemoError("CSGO/source1 demos are not supported (CS2 only)")
    is_cs2 = stamp.startswith(CS2_STAMP) or version_name == "valve_demo_2"
    if not is_cs2:
        raise UnsupportedDemoError(
            f"unsupported demo format (not CS2): stamp={stamp!r} version={version_name!r}"
        )

    map_name = header.get("map_name")
    if not map_name:
        raise UnsupportedDemoError("demo header has no map_name")

    is_gotv = header.get("client_name") == GOTV_CLIENT
    if not is_gotv:
        raise UnsupportedDemoError(
            "POV (client-recorded) demos are not supported — provide a GOTV/SourceTV demo"
        )

    return Classification(
        map_name=str(map_name),
        is_gotv=True,
        demo_type="gotv",
        demo_version=version_name,
        # tickrate isn't in the CS2 header; inferred post-parse (parse_report) — CS2 GOTV is 64.
        tickrate=_int_or_none(header.get("tickrate")),
        header=header,
    )


def classify_demo(dem_path: str) -> Classification:
    """Parse only the header of `dem_path` and classify it (the production entry point)."""
    from awpy import Demo

    dem = Demo(path=dem_path, verbose=False)
    return classify_header(dem.parse_header())
