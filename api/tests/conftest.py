"""Shared test fixtures.

DB fixtures spin up an isolated `demoviewer_test` database on the dev Percona (created via
root, from deploy/compose.dev.yml) so integration tests never touch dev/prod data. Each
test that needs a DB gets a pristine, freshly-created database (drop+create per test) — no
cross-test bleed, no truncation bookkeeping. Tests are skipped cleanly when no test MySQL is
reachable (e.g. CI without the dev stack), per TESTING.md.
"""
import asyncio
import os

import aiomysql
import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient

import app.db as db_module
import app.redis as redis_module
from app.config import settings
from app.db import create_pool
from app.main import app
from app.storage.migrate import apply_migrations

ADMIN_TEST_TOKEN = "test-admin-secret"

# Root creds match deploy/compose.dev.yml; override via env for other test stacks.
TEST_DB_NAME = os.environ.get("TEST_DB_NAME", "demoviewer_test")
TEST_ROOT_USER = os.environ.get("TEST_DB_ROOT_USER", "root")
TEST_ROOT_PASSWORD = os.environ.get("TEST_DB_ROOT_PASSWORD", "devroot")


def _root_kwargs(db: str | None = None) -> dict:
    kw = dict(host=settings.db_host, port=settings.db_port,
              user=TEST_ROOT_USER, password=TEST_ROOT_PASSWORD, connect_timeout=3)
    if db:
        kw["db"] = db
    return kw


def _probe_db() -> bool:
    async def _try() -> bool:
        try:
            conn = await aiomysql.connect(**_root_kwargs())
            conn.close()
            return True
        except Exception:
            return False
    return asyncio.run(_try())


DB_AVAILABLE = _probe_db()
requires_db = pytest.mark.skipif(not DB_AVAILABLE, reason="no test MySQL reachable")


async def _recreate_test_db() -> None:
    conn = await aiomysql.connect(autocommit=True, **_root_kwargs())
    try:
        async with conn.cursor() as cur:
            await cur.execute(f"DROP DATABASE IF EXISTS `{TEST_DB_NAME}`")
            await cur.execute(
                f"CREATE DATABASE `{TEST_DB_NAME}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    finally:
        conn.close()


async def _test_pool() -> aiomysql.Pool:
    return await create_pool(
        user=TEST_ROOT_USER, password=TEST_ROOT_PASSWORD, db=TEST_DB_NAME
    )


@pytest.fixture
async def client():
    """An ASGI client bound to the FastAPI app (no network)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def empty_db():
    """A freshly-created, *un-migrated* test database. Yields a root-bound pool."""
    if not DB_AVAILABLE:
        pytest.skip("no test MySQL reachable")
    await _recreate_test_db()
    pool = await _test_pool()
    try:
        yield pool
    finally:
        pool.close()
        await pool.wait_closed()


@pytest.fixture
async def db(empty_db):
    """A freshly-created test database with all migrations + the map seed applied."""
    await apply_migrations(empty_db)
    return empty_db


@pytest.fixture
def fake_redis():
    """An in-memory async Redis (no server needed) for the key-lookup cache."""
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def admin_headers() -> dict:
    """Headers carrying the test admin token (matches the `api` fixture's monkeypatch)."""
    return {"X-Admin-Token": ADMIN_TEST_TOKEN}


@pytest.fixture
async def api(db, fake_redis, monkeypatch):
    """ASGI client with the app wired to the isolated test DB + fake Redis + a known
    admin token. Drives auth/admin end-to-end without touching dev/prod infra."""
    monkeypatch.setattr(db_module, "_pool", db)
    monkeypatch.setattr(redis_module, "_redis", fake_redis)
    monkeypatch.setattr(settings, "admin_token", ADMIN_TEST_TOKEN)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
