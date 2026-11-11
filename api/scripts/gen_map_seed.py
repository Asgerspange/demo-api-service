"""Generate migrations/002_seed_map_metadata.sql from the authoritative map_metadata.sql.

`map_metadata.sql` (repo root) is the source of truth for map calibration + bunny CDN
radar URLs (it supersedes scales.js). Its INSERT uses the legacy column order and carries
`id`/`created_at`/`updated_at` columns our schema drops. This script re-projects each row
onto our `map_metadata` columns, preserving every value's *raw* SQL literal (so the escaped
`selections` JSON and NULLs pass through verbatim, no re-escaping bugs) and emits an
idempotent `INSERT ... ON DUPLICATE KEY UPDATE` seed migration.

Run from api/:  uv run python scripts/gen_map_seed.py
Re-run whenever map_metadata.sql changes; commit the regenerated 002 file.
"""
from pathlib import Path

# Column order as it appears in map_metadata.sql's INSERT statement.
SRC_COLS = [
    "id", "map_id", "display_name", "name", "is_active_duty", "pos_x", "pos_y",
    "scale", "rotate", "zoom", "selections", "image_path", "created_at", "updated_at",
]
# Columns we seed, in our schema's order (id is AUTO_INCREMENT; timestamps dropped).
DST_COLS = [
    "map_id", "name", "display_name", "is_active_duty", "pos_x", "pos_y",
    "scale", "rotate", "zoom", "selections", "image_path",
]

ROOT = Path(__file__).resolve().parents[2]      # repo root (…/demoviewer)
SRC = ROOT / "map_metadata.sql"
OUT = Path(__file__).resolve().parents[1] / "migrations" / "002_seed_map_metadata.sql"


def _extract_values_blob(sql: str) -> str:
    """Return the substring between `VALUES` and the terminating `;` of the INSERT."""
    upper = sql.upper()
    start = upper.index("VALUES", upper.index("INSERT INTO `MAP_METADATA`")) + len("VALUES")
    end = sql.index(";", start)
    return sql[start:end]


def _split_top_level(s: str, sep: str) -> list[str]:
    """Split `s` on `sep` at paren-depth 0, respecting single-quoted strings and \\ escapes."""
    out, buf, depth, in_str, esc = [], [], 0, False, False
    for ch in s:
        if esc:
            buf.append(ch)
            esc = False
            continue
        if ch == "\\":
            buf.append(ch)
            esc = True
            continue
        if in_str:
            buf.append(ch)
            if ch == "'":
                in_str = False
            continue
        if ch == "'":
            in_str = True
            buf.append(ch)
        elif ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == sep and depth == 0:
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out


def _parse_rows(blob: str) -> list[list[str]]:
    """Parse `(...),(...)` into rows of raw token strings (one per source column).

    Walks the blob splitting on balanced top-level `(...)` groups (quote/escape aware),
    then comma-splits each group's interior at depth 0.
    """
    rows: list[list[str]] = []
    depth, in_str, esc, buf = 0, False, False, []
    for ch in blob:
        if esc:
            buf.append(ch); esc = False; continue
        if ch == "\\":
            buf.append(ch); esc = True; continue
        if in_str:
            buf.append(ch)
            if ch == "'":
                in_str = False
            continue
        if ch == "'":
            in_str = True; buf.append(ch); continue
        if ch == "(":
            depth += 1
            if depth == 1:
                buf = []
                continue
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            if depth == 0:
                tokens = [t.strip() for t in _split_top_level("".join(buf), ",")]
                rows.append(tokens)
            else:
                buf.append(ch)
        else:
            if depth >= 1:
                buf.append(ch)
    return rows


def main() -> None:
    sql = SRC.read_text(encoding="utf-8")
    rows = _parse_rows(_extract_values_blob(sql))
    src_idx = {c: i for i, c in enumerate(SRC_COLS)}

    out_rows = []
    for tokens in rows:
        if len(tokens) != len(SRC_COLS):
            raise SystemExit(f"row has {len(tokens)} cols, expected {len(SRC_COLS)}: {tokens}")
        out_rows.append("(" + ", ".join(tokens[src_idx[c]] for c in DST_COLS) + ")")

    col_list = ", ".join(f"`{c}`" for c in DST_COLS)
    # Idempotent: re-running the migration (or seed) keeps calibration in sync with the file.
    update = ", ".join(f"`{c}`=VALUES(`{c}`)" for c in DST_COLS if c != "name")
    body = (
        "-- Stage 02 — map_metadata seed. GENERATED from map_metadata.sql by\n"
        "-- scripts/gen_map_seed.py — do not edit by hand; re-run the generator instead.\n"
        f"-- {len(out_rows)} maps; `name` is the natural key. Idempotent (upsert on name).\n\n"
        f"INSERT INTO map_metadata ({col_list}) VALUES\n"
        + ",\n".join(out_rows)
        + f"\nON DUPLICATE KEY UPDATE {update};\n"
    )
    OUT.write_text(body, encoding="utf-8")
    print(f"wrote {OUT} ({len(out_rows)} maps)")


if __name__ == "__main__":
    main()
