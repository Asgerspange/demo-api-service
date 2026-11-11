"""Apply database migrations against the configured DB.

    uv run python scripts/migrate.py

Idempotent: tracks applied files in `schema_migrations` and runs only pending ones.
Creates tables (001) and seeds map_metadata (002) on a fresh `demoviewer` database.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable

from app.db import close_pool, get_pool
from app.storage.migrate import apply_migrations


async def main() -> None:
    pool = await get_pool()
    try:
        applied = await apply_migrations(pool)
    finally:
        await close_pool()
    if applied:
        print("applied migrations:", ", ".join(applied))
    else:
        print("no pending migrations — schema up to date")


if __name__ == "__main__":
    asyncio.run(main())
