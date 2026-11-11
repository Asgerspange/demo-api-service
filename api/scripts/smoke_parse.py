"""Parser toolchain smoke test — the day-one de-risk.

Confirms the awpy fork parses a CS2 demo, exposes `.compress()`, and produces the
dataframes the old demo_processor.py relies on.

    uv run python scripts/smoke_parse.py ../demoparser2/src/parser/test_demo.dem
"""
import sys

from awpy import Demo


def main(path: str) -> int:
    print(f"Parsing: {path}")
    dem = Demo(path=path, verbose=False)
    dem.parse()

    header = getattr(dem, "header", {}) or {}
    print("map_name      :", header.get("map_name"))
    print("has .compress :", hasattr(dem, "compress"))

    expected = ["kills", "rounds", "ticks", "grenades", "smokes", "infernos", "bomb", "shots"]
    print("\ndataframes:")
    missing = []
    for name in expected:
        df = getattr(dem, name, None)
        shape = getattr(df, "shape", None)
        print(f"  {name:10s} {type(df).__name__:10s} shape={shape}")
        if df is None:
            missing.append(name)

    print("\nRESULT:", "OK" if header.get("map_name") and not missing else "CHECK OUTPUT")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: smoke_parse.py <path-to-.dem>")
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
