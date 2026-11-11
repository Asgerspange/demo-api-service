#!/usr/bin/env python
"""Disaster-recovery CLI: rebuild the demo→object mapping by scanning storage (Stage 16 §16.3).

Use ONLY when the DB mapping is lost and can't be restored from backup (see deploy/DR.md) — the
normal recovery is a DB restore. This walks the demos zone, reads each `index.json`, and re-creates
the `demos` + `demo_rounds` rows pointing at the surviving payload objects, owned by `--owner`.

    cd api && uv run python scripts/rebuild_from_storage.py --owner 1 [--payload-version 1]

Requires the bunny storage env (BUNNY_DEMOS_*). Idempotent — safe to re-run.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import close_pool, get_pool  # noqa: E402
from app.dr import rebuild_from_storage  # noqa: E402
from app.storage.object_store import object_store  # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(description="Rebuild demo mapping from storage (DR).")
    ap.add_argument("--owner", type=int, required=True, help="user id to own the recovered demos")
    ap.add_argument("--payload-version", type=int, default=None)
    args = ap.parse_args()

    pool = await get_pool()
    try:
        summary = await rebuild_from_storage(
            pool, object_store(), owner_user_id=args.owner,
            payload_version=args.payload_version)
    finally:
        await close_pool()
    print(f"rebuild complete: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
