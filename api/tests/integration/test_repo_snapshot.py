"""Regression: pooled read connections must not pin a stale MVCC snapshot.

With autocommit off and MySQL's default REPEATABLE READ, a connection's first SELECT fixes a
snapshot that stays frozen until the transaction ends. If the read helpers never commit, a
long-lived pooled connection keeps serving rows as they looked when it first read — so data
another connection commits afterward is invisible (this is what made freshly-issued API keys
fail to authenticate on a long-running server). The repos commit after each read to release
the snapshot; this test fails without that fix.
"""
import os

import pytest

from app.config import settings
from app.db import create_pool
from app.storage.repos import UserRepo

pytestmark = pytest.mark.integration

TEST_DB_NAME = os.environ.get("TEST_DB_NAME", "demoviewer_test")
ROOT_USER = os.environ.get("TEST_DB_ROOT_USER", "root")
ROOT_PW = os.environ.get("TEST_DB_ROOT_PASSWORD", "devroot")


async def test_pooled_read_sees_externally_committed_row(db):
    # A reader pool pinned to ONE connection, so the same connection serves both reads.
    reader = await create_pool(user=ROOT_USER, password=ROOT_PW, db=TEST_DB_NAME,
                               minsize=1, maxsize=1)
    try:
        reader_repo = UserRepo(reader)
        # First read establishes the connection's transaction snapshot.
        assert await reader_repo.get_by_email("late@x.com") is None
        # A *different* connection inserts + commits the row.
        await UserRepo(db).create("late@x.com")
        # The pinned connection must now see it (would be None under a frozen snapshot).
        row = await reader_repo.get_by_email("late@x.com")
        assert row is not None and row["email"] == "late@x.com"
    finally:
        reader.close()
        await reader.wait_closed()
