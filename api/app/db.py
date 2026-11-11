"""aiomysql connection pool — one shared pool per process.

The pool is created lazily on first use and reused by the API (request handlers via
`get_pool()`) and the arq worker (acquired in its `startup`). Repos in `app/storage/`
take a pool and acquire/release connections per call. autocommit is OFF — repos commit
explicitly so multi-statement writes stay atomic.
"""
from __future__ import annotations

import aiomysql

from .config import settings

_pool: aiomysql.Pool | None = None


async def create_pool(**overrides) -> aiomysql.Pool:
    """Create a new aiomysql pool from settings (overridable for tests)."""
    opts = dict(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        db=settings.db_name,
        charset="utf8mb4",
        autocommit=False,
        minsize=1,
        maxsize=10,
        pool_recycle=3600,  # avoid MySQL's idle wait_timeout dropping connections
    )
    opts.update(overrides)
    return await aiomysql.create_pool(**opts)


async def get_pool() -> aiomysql.Pool:
    """Return the process-wide pool, creating it on first use."""
    global _pool
    if _pool is None:
        _pool = await create_pool()
    return _pool


async def close_pool() -> None:
    """Close the process-wide pool (call on shutdown)."""
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None
