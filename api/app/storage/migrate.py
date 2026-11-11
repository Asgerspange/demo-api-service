"""Lightweight forward-only SQL migration runner (no ORM).

Applies `migrations/*.sql` in filename order, tracking applied files in a
`schema_migrations` table so each runs exactly once. The map_metadata seed (002) is
written as an idempotent upsert, so re-applying it after a maps change is safe — but
the tracker still skips already-applied files on the normal path.

Each `.sql` file may contain multiple statements separated by `;`. We split on `;`
respecting single-quoted strings + backslash escapes (the seed's JSON contains commas
and quotes but no semicolons, so this is robust for our controlled SQL).
"""
from __future__ import annotations

from pathlib import Path

import aiomysql

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"

_CREATE_TRACKER = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  filename   VARCHAR(255) NOT NULL PRIMARY KEY,
  applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def split_statements(sql: str) -> list[str]:
    """Split a SQL script into statements on `;` at top level.

    Quote/escape aware and comment aware: a `;` inside a single-quoted string, a `--`/`#`
    line comment, or a `/* */` block comment does NOT terminate a statement. Comments are
    dropped from the emitted statements.
    """
    stmts: list[str] = []
    buf: list[str] = []
    i, n = 0, len(sql)
    in_str = esc = False
    while i < n:
        ch = sql[i]
        if in_str:
            buf.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == "'":
                in_str = False
            i += 1
            continue
        # line comment: `-- ` or `#` → skip to end of line
        if (ch == "-" and sql[i:i + 2] == "--" and (i + 2 >= n or sql[i + 2] in " \t\r\n")) \
                or ch == "#":
            nl = sql.find("\n", i)
            i = n if nl == -1 else nl
            continue
        # block comment: `/* ... */`
        if ch == "/" and sql[i:i + 2] == "/*":
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        if ch == "'":
            in_str = True
            buf.append(ch)
        elif ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []
        else:
            buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def _migration_files(migrations_dir: Path) -> list[Path]:
    return sorted(p for p in migrations_dir.glob("*.sql") if p.is_file())


async def apply_migrations(
    pool: aiomysql.Pool, migrations_dir: Path | None = None
) -> list[str]:
    """Apply all pending migrations. Returns the list of filenames applied this run."""
    migrations_dir = migrations_dir or MIGRATIONS_DIR
    # Fail LOUD on a missing/empty migrations dir — silently finding zero `.sql` files (e.g. the
    # directory wasn't copied into the image) would leave a DB with no tables and report success.
    files = _migration_files(migrations_dir)
    if not files:
        raise RuntimeError(
            f"no migration files found in {migrations_dir} — the migrations directory is missing "
            "or empty (is it COPYed into the image?)"
        )
    applied_now: list[str] = []

    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(_CREATE_TRACKER)
            await cur.execute("SELECT filename FROM schema_migrations")
            done = {row[0] for row in await cur.fetchall()}
        await conn.commit()

        for path in files:
            if path.name in done:
                continue
            statements = split_statements(path.read_text(encoding="utf-8"))
            async with conn.cursor() as cur:
                for stmt in statements:
                    await cur.execute(stmt)
                await cur.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,)
                )
            await conn.commit()
            applied_now.append(path.name)

    return applied_now
