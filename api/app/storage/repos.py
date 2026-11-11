"""Async DB repositories — thin, explicit SQL over aiomysql (no ORM, Stage 2.4).

Each repo wraps a pool and acquires a connection per call. autocommit is off, so writes
commit explicitly. JSON columns are dumped on write and loaded on read (MySQL returns JSON
as text). Repos return plain dicts (DictCursor) so callers stay decoupled from the driver.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

import aiomysql


def _loads(value: Any) -> Any:
    """Decode a JSON column (aiomysql returns it as str/bytes) into Python."""
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    return json.loads(value)


def _dumps(value: Any) -> str | None:
    return None if value is None else json.dumps(value)


class _Repo:
    def __init__(self, pool: aiomysql.Pool) -> None:
        self.pool = pool

    async def _fetchone(self, sql: str, args: Iterable = ()) -> dict | None:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql, tuple(args))
                row = await cur.fetchone()
            await conn.commit()  # end the read txn so the next SELECT gets a fresh snapshot
            return row

    async def _fetchall(self, sql: str, args: Iterable = ()) -> list[dict]:
        async with self.pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql, tuple(args))
                rows = list(await cur.fetchall())
            await conn.commit()  # end the read txn so the next SELECT gets a fresh snapshot
            return rows

    async def _execute(self, sql: str, args: Iterable = ()) -> int:
        """Run a write; return lastrowid (for INSERTs) and commit."""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, tuple(args))
                rowid = cur.lastrowid
            await conn.commit()
            return rowid


# Sentinel so partial updates can distinguish "leave unchanged" from "set to NULL".
_UNSET: Any = object()


class UserRepo(_Repo):
    async def create(self, email: str, display_name: str | None = None,
                     status: str = "active") -> int:
        return await self._execute(
            "INSERT INTO users (email, display_name, status) VALUES (%s, %s, %s)",
            (email, display_name, status),
        )

    async def get(self, user_id: int) -> dict | None:
        return await self._fetchone("SELECT * FROM users WHERE id = %s", (user_id,))

    async def get_by_email(self, email: str) -> dict | None:
        return await self._fetchone("SELECT * FROM users WHERE email = %s", (email,))

    async def list(self, limit: int = 100) -> list[dict]:
        return await self._fetchall(
            "SELECT * FROM users ORDER BY id DESC LIMIT %s", (limit,)
        )

    async def update(self, user_id: int, *, display_name: Any = _UNSET,
                     status: str | None = None, tier: str | None = None) -> None:
        sets, args = [], []
        if status is not None:
            sets.append("status = %s"); args.append(status)
        if tier is not None:
            sets.append("tier = %s"); args.append(tier)
        if display_name is not _UNSET:
            sets.append("display_name = %s"); args.append(display_name)
        if not sets:
            return
        args.append(user_id)
        await self._execute(f"UPDATE users SET {', '.join(sets)} WHERE id = %s", args)

    async def set_webhook_secret(self, user_id: int, secret: str) -> None:
        """Set/rotate the per-user HMAC secret used to sign outbound webhooks (Stage 16 §16.2)."""
        await self._execute(
            "UPDATE users SET webhook_secret = %s WHERE id = %s", (secret, user_id)
        )


class KeyRepo(_Repo):
    async def create(self, user_id: int, kind: str, prefix: str, key_hash: str,
                     last4: str, allowed_origins: list[str],
                     rate_per_hour: int | None = None) -> int:
        return await self._execute(
            "INSERT INTO api_keys (user_id, kind, prefix, key_hash, last4, "
            "allowed_origins, rate_per_hour) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (user_id, kind, prefix, key_hash, last4, _dumps(allowed_origins), rate_per_hour),
        )

    async def get(self, key_id: int) -> dict | None:
        row = await self._fetchone("SELECT * FROM api_keys WHERE id = %s", (key_id,))
        if row:
            row["allowed_origins"] = _loads(row["allowed_origins"])
        return row

    async def get_by_hash(self, key_hash: str) -> dict | None:
        """Active key by hash, joined with its owner's status (a suspended owner's keys are
        rejected by the auth service). Expiry is checked by the service against now()."""
        row = await self._fetchone(
            "SELECT k.*, u.status AS user_status FROM api_keys k "
            "JOIN users u ON u.id = k.user_id "
            "WHERE k.key_hash = %s AND k.status = 'active'",
            (key_hash,),
        )
        if row:
            row["allowed_origins"] = _loads(row["allowed_origins"])
        return row

    async def list_all(self) -> list[dict]:
        rows = await self._fetchall("SELECT * FROM api_keys ORDER BY id")
        for r in rows:
            r["allowed_origins"] = _loads(r["allowed_origins"])
        return rows

    async def list_for_user(self, user_id: int) -> list[dict]:
        rows = await self._fetchall(
            "SELECT * FROM api_keys WHERE user_id = %s ORDER BY id", (user_id,)
        )
        for r in rows:
            r["allowed_origins"] = _loads(r["allowed_origins"])
        return rows

    async def set_attrs(self, key_id: int, *, allowed_origins: list[str] | None = None,
                        rate_per_hour: Any = _UNSET) -> None:
        sets, args = [], []
        if allowed_origins is not None:
            sets.append("allowed_origins = %s"); args.append(_dumps(allowed_origins))
        if rate_per_hour is not _UNSET:
            sets.append("rate_per_hour = %s"); args.append(rate_per_hour)
        if not sets:
            return
        args.append(key_id)
        await self._execute(f"UPDATE api_keys SET {', '.join(sets)} WHERE id = %s", args)

    async def begin_rotation(self, key_id: int, grace_seconds: int,
                             rotated_to: int) -> None:
        """Mark a key for grace expiry after it has been rotated to `rotated_to`."""
        await self._execute(
            "UPDATE api_keys SET expires_at = DATE_ADD(CURRENT_TIMESTAMP, INTERVAL %s SECOND), "
            "rotated_to = %s WHERE id = %s",
            (grace_seconds, rotated_to, key_id),
        )

    async def revoke(self, key_id: int) -> None:
        await self._execute(
            "UPDATE api_keys SET status = 'revoked', revoked_at = CURRENT_TIMESTAMP "
            "WHERE id = %s",
            (key_id,),
        )


class DemoRepo(_Repo):
    async def create(self, owner_user_id: int, sha256: str, map: str, name: str,
                     status: str = "queued", payload_version: int = 1,
                     **optional: Any) -> int:
        cols = ["owner_user_id", "sha256", "map", "name", "status", "payload_version"]
        vals: list[Any] = [owner_user_id, sha256, map, name, status, payload_version]
        for col, val in optional.items():
            cols.append(col)
            vals.append(_dumps(val) if col == "meta" else val)
        placeholders = ", ".join(["%s"] * len(cols))
        demo_id = await self._execute(
            f"INSERT INTO demos ({', '.join(cols)}) VALUES ({placeholders})", vals
        )
        # The creator can always read what it created (demo_access is the read gate now).
        await self.grant_access(demo_id, owner_user_id)
        # Mirror any collection pointer into the membership table (the listing source of truth).
        if optional.get("collection_id") is not None:
            await self.add_to_collection(demo_id, optional["collection_id"])
        return demo_id

    async def get(self, demo_id: int) -> dict | None:
        row = await self._fetchone("SELECT * FROM demos WHERE id = %s", (demo_id,))
        if row:
            row["meta"] = _loads(row["meta"])
        return row

    async def get_by_sha256(self, sha256: str) -> dict | None:
        row = await self._fetchone("SELECT * FROM demos WHERE sha256 = %s", (sha256,))
        if row:
            row["meta"] = _loads(row["meta"])
        return row

    async def get_for_user(self, demo_id: int, user_id: int) -> dict | None:
        """A demo the user has access to (via demo_access), else None → 404. Reads go through
        this instead of a bare owner_user_id compare so deduped demos shared across tenants
        resolve for every tenant that was granted access."""
        row = await self._fetchone(
            "SELECT d.* FROM demos d JOIN demo_access a ON a.demo_id = d.id "
            "WHERE d.id = %s AND a.user_id = %s",
            (demo_id, user_id),
        )
        if row:
            row["meta"] = _loads(row["meta"])
        return row

    async def grant_access(self, demo_id: int, user_id: int) -> None:
        """Grant a tenant access to a demo (idempotent). Called on create and on every dedup
        hit, so an identical demo ingested by a second tenant is visible to them too."""
        await self._execute(
            "INSERT INTO demo_access (demo_id, user_id) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE user_id = user_id",
            (demo_id, user_id),
        )

    async def update_status(self, demo_id: int, status: str,
                            error: str | None = None) -> None:
        await self._execute(
            "UPDATE demos SET status = %s, error = %s WHERE id = %s",
            (status, error, demo_id),
        )

    async def set_raw_archive(self, demo_id: int, *, raw_storage_key: str,
                              raw_codec: str, raw_bytes: int) -> None:
        """Record the cold-tier archival of the raw `.dem` (Stage 05 step 5 / Stage 10)."""
        await self._execute(
            "UPDATE demos SET raw_storage_key = %s, raw_codec = %s, raw_bytes = %s "
            "WHERE id = %s",
            (raw_storage_key, raw_codec, raw_bytes, demo_id),
        )

    async def set_ready(self, demo_id: int, *, round_count: int, duration_ticks: int,
                        storage_key: str, meta: dict | None = None) -> None:
        await self._execute(
            "UPDATE demos SET status = 'ready', round_count = %s, duration_ticks = %s, "
            "storage_key = %s, meta = %s, ready_at = CURRENT_TIMESTAMP WHERE id = %s",
            (round_count, duration_ticks, storage_key, _dumps(meta), demo_id),
        )

    async def delete(self, demo_id: int) -> None:
        """Delete a demo row. demo_rounds + demo_external_refs cascade (FK ON DELETE CASCADE);
        callers must first clear any ingest_jobs.demo_id pointing here (no cascade there)."""
        await self._execute("DELETE FROM demos WHERE id = %s", (demo_id,))

    async def set_payload_version(self, demo_id: int, payload_version: int) -> None:
        """Flip a demo to a new payload_version after a verified backfill (Stage 14 §14.2)."""
        await self._execute(
            "UPDATE demos SET payload_version = %s WHERE id = %s", (payload_version, demo_id)
        )

    async def list_ids_for_backfill(self, *, payload_version: int | None = None) -> list[int]:
        """Ready demos to backfill — optionally only those not already at the target version."""
        if payload_version is not None:
            rows = await self._fetchall(
                "SELECT id FROM demos WHERE status = 'ready' AND payload_version <> %s ORDER BY id",
                (payload_version,),
            )
        else:
            rows = await self._fetchall(
                "SELECT id FROM demos WHERE status = 'ready' ORDER BY id"
            )
        return [int(r["id"]) for r in rows]

    async def list_for_collection(self, collection_id: int) -> list[dict]:
        """All demos in a collection (an archive's maps), oldest first (Stage 18). Reads the
        many-to-many membership so a demo shared across tenants appears in each one's collection."""
        rows = await self._fetchall(
            "SELECT d.* FROM demos d JOIN collection_demos cd ON cd.demo_id = d.id "
            "WHERE cd.collection_id = %s ORDER BY d.id",
            (collection_id,),
        )
        for r in rows:
            r["meta"] = _loads(r["meta"])
        return rows

    async def add_to_collection(self, demo_id: int, collection_id: int) -> None:
        """Add a demo to a collection (idempotent, many-to-many). This is the membership source of
        truth for listing; it lets a shared/deduped demo belong to several tenants' collections."""
        await self._execute(
            "INSERT INTO collection_demos (collection_id, demo_id) VALUES (%s, %s) "
            "ON DUPLICATE KEY UPDATE demo_id = demo_id",
            (collection_id, demo_id),
        )

    async def set_collection(self, demo_id: int, collection_id: int) -> None:
        """Set the demo's (creating-tenant) collection pointer AND register membership."""
        await self._execute(
            "UPDATE demos SET collection_id = %s WHERE id = %s", (collection_id, demo_id)
        )
        await self.add_to_collection(demo_id, collection_id)

    async def list_for_user(self, user_id: int, limit: int = 50,
                            before_id: int | None = None, *,
                            map_name: str | None = None,
                            status: str | None = None) -> list[dict]:
        """Cursor-paginated (id-descending) list of the demos a user can access (Stage 06,
        access via demo_access so shared/deduped demos are included).

        `before_id` is the opaque cursor (return rows with a smaller id); `map_name`/`status`
        are optional filters. All conditions are ANDed into one indexed query.
        """
        where = ["a.user_id = %s"]
        args: list[Any] = [user_id]
        if before_id is not None:
            where.append("d.id < %s"); args.append(before_id)
        if map_name is not None:
            where.append("d.map = %s"); args.append(map_name)
        if status is not None:
            where.append("d.status = %s"); args.append(status)
        args.append(limit)
        rows = await self._fetchall(
            f"SELECT d.* FROM demos d JOIN demo_access a ON a.demo_id = d.id "
            f"WHERE {' AND '.join(where)} ORDER BY d.id DESC LIMIT %s",
            args,
        )
        for r in rows:
            r["meta"] = _loads(r["meta"])
        return rows


class RoundRepo(_Repo):
    async def upsert(self, demo_id: int, round_index: int, storage_key: str,
                     byte_size: int, meta: dict) -> None:
        await self._execute(
            "INSERT INTO demo_rounds (demo_id, round_index, storage_key, byte_size, meta) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE storage_key = VALUES(storage_key), "
            "byte_size = VALUES(byte_size), meta = VALUES(meta)",
            (demo_id, round_index, storage_key, byte_size, _dumps(meta)),
        )

    async def get(self, demo_id: int, round_index: int) -> dict | None:
        row = await self._fetchone(
            "SELECT * FROM demo_rounds WHERE demo_id = %s AND round_index = %s",
            (demo_id, round_index),
        )
        if row:
            row["meta"] = _loads(row["meta"])
        return row

    async def list_for_demo(self, demo_id: int) -> list[dict]:
        rows = await self._fetchall(
            "SELECT * FROM demo_rounds WHERE demo_id = %s ORDER BY round_index", (demo_id,)
        )
        for r in rows:
            r["meta"] = _loads(r["meta"])
        return rows


class RefRepo(_Repo):
    """demo_external_refs — dynamic per-source identifiers (HLTV/faceit/…)."""

    async def add(self, demo_id: int, source: str, external_id: str, user_id: int) -> None:
        # Refs are tenant-scoped: idempotent per (demo_id, source, external_id, user_id). Two tenants
        # may attach the same match id to the same (deduped/shared) demo — one row each — so each sees
        # only its own refs and a shared demo never leaks another tenant's ids.
        await self._execute(
            "INSERT INTO demo_external_refs (demo_id, source, external_id, user_id) "
            "VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE external_id = VALUES(external_id)",
            (demo_id, source, external_id, user_id),
        )

    async def resolve(self, source: str, external_id: str, user_id: int) -> dict | None:
        """First demo a tenant's ref maps to (back-compat single lookup). Use resolve_all for maps."""
        return await self._fetchone(
            "SELECT * FROM demo_external_refs WHERE source = %s AND external_id = %s "
            "AND user_id = %s ORDER BY id",
            (source, external_id, user_id),
        )

    async def resolve_all(self, source: str, external_id: str, user_id: int) -> list[dict]:
        """Every demo a tenant's (source, external_id) maps to — one match id → all its maps (§18.3),
        scoped to the requesting tenant so refs never resolve across tenants."""
        return await self._fetchall(
            "SELECT * FROM demo_external_refs WHERE source = %s AND external_id = %s "
            "AND user_id = %s ORDER BY id",
            (source, external_id, user_id),
        )

    async def list_for_demo(self, demo_id: int, user_id: int) -> list[dict]:
        return await self._fetchall(
            "SELECT * FROM demo_external_refs WHERE demo_id = %s AND user_id = %s ORDER BY id",
            (demo_id, user_id),
        )


class JobRepo(_Repo):
    async def create(self, job_id: str, source_type: str, source_ref: str,
                     user_id: int | None = None, status: str = "queued",
                     webhook_url: str | None = None) -> str:
        await self._execute(
            "INSERT INTO ingest_jobs (id, user_id, source_type, source_ref, status, "
            "webhook_url) VALUES (%s, %s, %s, %s, %s, %s)",
            (job_id, user_id, source_type, source_ref, status, webhook_url),
        )
        return job_id

    async def get(self, job_id: str) -> dict | None:
        row = await self._fetchone("SELECT * FROM ingest_jobs WHERE id = %s", (job_id,))
        if row:
            row["progress"] = _loads(row["progress"])
        return row

    async def clear_demo(self, demo_id: int) -> None:
        """Null out the demo pointer on any jobs referencing it (so the demo can be deleted)."""
        await self._execute(
            "UPDATE ingest_jobs SET demo_id = NULL WHERE demo_id = %s", (demo_id,)
        )

    async def delete(self, job_id: str) -> None:
        """Delete a job row (used to drop an idempotency-race-loser duplicate, Stage 16)."""
        await self._execute("DELETE FROM ingest_jobs WHERE id = %s", (job_id,))

    async def counts_by_status(self) -> dict[str, int]:
        """Job counts grouped by status — admin visibility + the queue-depth-ish gauge."""
        rows = await self._fetchall(
            "SELECT status, COUNT(*) AS n FROM ingest_jobs GROUP BY status"
        )
        return {r["status"]: int(r["n"]) for r in rows}

    async def list_recent(self, limit: int = 50, status: str | None = None) -> list[dict]:
        """Recent ingest jobs (optionally filtered) for the admin dashboard."""
        if status:
            rows = await self._fetchall(
                "SELECT * FROM ingest_jobs WHERE status = %s ORDER BY created_at DESC LIMIT %s",
                (status, limit),
            )
        else:
            rows = await self._fetchall(
                "SELECT * FROM ingest_jobs ORDER BY created_at DESC LIMIT %s", (limit,)
            )
        for r in rows:
            r["progress"] = _loads(r["progress"])
        return rows

    async def update(self, job_id: str, *, status: str | None = None,
                     demo_id: int | None = None, progress: dict | None = None,
                     error: str | None = None) -> None:
        sets, args = [], []
        if status is not None:
            sets.append("status = %s"); args.append(status)
        if demo_id is not None:
            sets.append("demo_id = %s"); args.append(demo_id)
        if progress is not None:
            sets.append("progress = %s"); args.append(_dumps(progress))
        if error is not None:
            sets.append("error = %s"); args.append(error)
        if not sets:
            return
        args.append(job_id)
        await self._execute(
            f"UPDATE ingest_jobs SET {', '.join(sets)} WHERE id = %s", args
        )


class BackfillRepo(_Repo):
    """Resumable backfill run + per-demo state (Stage 14)."""

    async def create_run(self, target_payload_version: int, mode: str,
                         demo_ids: Iterable[int]) -> int:
        ids = list(demo_ids)
        run_id = await self._execute(
            "INSERT INTO backfill_runs (target_payload_version, mode, total) VALUES (%s, %s, %s)",
            (target_payload_version, mode, len(ids)),
        )
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                for demo_id in ids:
                    await cur.execute(
                        "INSERT IGNORE INTO backfill_demos (run_id, demo_id) VALUES (%s, %s)",
                        (run_id, demo_id),
                    )
            await conn.commit()
        return run_id

    async def get_run(self, run_id: int) -> dict | None:
        return await self._fetchone("SELECT * FROM backfill_runs WHERE id = %s", (run_id,))

    async def state(self, run_id: int, demo_id: int) -> str | None:
        row = await self._fetchone(
            "SELECT state FROM backfill_demos WHERE run_id = %s AND demo_id = %s",
            (run_id, demo_id),
        )
        return row["state"] if row else None

    async def mark(self, run_id: int, demo_id: int, state: str,
                   error: str | None = None) -> None:
        await self._execute(
            "UPDATE backfill_demos SET state = %s, error = %s WHERE run_id = %s AND demo_id = %s",
            (state, error, run_id, demo_id),
        )

    async def pending(self, run_id: int) -> list[int]:
        rows = await self._fetchall(
            "SELECT demo_id FROM backfill_demos WHERE run_id = %s AND state = 'pending' ORDER BY demo_id",
            (run_id,),
        )
        return [int(r["demo_id"]) for r in rows]

    async def counts(self, run_id: int) -> dict[str, int]:
        rows = await self._fetchall(
            "SELECT state, COUNT(*) AS n FROM backfill_demos WHERE run_id = %s GROUP BY state",
            (run_id,),
        )
        return {r["state"]: int(r["n"]) for r in rows}

    async def failures(self, run_id: int, limit: int = 100) -> list[dict]:
        return await self._fetchall(
            "SELECT demo_id, error FROM backfill_demos WHERE run_id = %s AND state = 'failed' "
            "ORDER BY demo_id LIMIT %s",
            (run_id, limit),
        )

    async def set_run_status(self, run_id: int, status: str) -> None:
        await self._execute(
            "UPDATE backfill_runs SET status = %s WHERE id = %s", (status, run_id)
        )


class CollectionRepo(_Repo):
    """Demo collections — an ingested archive/match grouping its per-map demos (Stage 18 §18.3)."""

    async def get(self, collection_id: int) -> dict | None:
        row = await self._fetchone("SELECT * FROM demo_collections WHERE id = %s", (collection_id,))
        if row:
            row["meta"] = _loads(row["meta"])
        return row

    async def resolve(self, owner_user_id: int, source: str, external_id: str) -> dict | None:
        row = await self._fetchone(
            "SELECT * FROM demo_collections WHERE owner_user_id = %s AND source = %s "
            "AND external_id = %s",
            (owner_user_id, source, external_id),
        )
        if row:
            row["meta"] = _loads(row["meta"])
        return row

    async def get_or_create(self, owner_user_id: int, *, source: str | None,
                            external_id: str | None, name: str | None = None) -> int:
        """Idempotent: a re-ingest of the same (owner, source, match) attaches to the same collection.

        A collection with no source/external_id (ad-hoc multi-demo upload) is always created fresh
        (NULLs are distinct in the unique index), so those never merge unexpectedly.
        """
        if source and external_id:
            existing = await self.resolve(owner_user_id, source, external_id)
            if existing:
                return int(existing["id"])
            # INSERT IGNORE so a concurrent ingest of the same match doesn't raise; re-resolve on a
            # lost race (lastrowid 0 → the unique key already had it).
            cid = await self._execute(
                "INSERT IGNORE INTO demo_collections (owner_user_id, source, external_id, name) "
                "VALUES (%s, %s, %s, %s)",
                (owner_user_id, source, external_id, name),
            )
            if cid:
                return int(cid)
            winner = await self.resolve(owner_user_id, source, external_id)
            return int(winner["id"])
        # Ad-hoc collection (no ref) — always fresh.
        return int(await self._execute(
            "INSERT INTO demo_collections (owner_user_id, source, external_id, name) "
            "VALUES (%s, %s, %s, %s)",
            (owner_user_id, source, external_id, name),
        ))


class IdempotencyRepo(_Repo):
    """Idempotency-key → job mapping for POST /ingest (Stage 16 §16.2)."""

    async def get_job(self, user_id: int, key: str) -> str | None:
        row = await self._fetchone(
            "SELECT job_id FROM ingest_idempotency WHERE user_id = %s AND idempotency_key = %s",
            (user_id, key),
        )
        return row["job_id"] if row else None

    async def put(self, user_id: int, key: str, job_id: str) -> str:
        """Bind (user, key) → job_id once. Concurrency-safe: if the key already exists (a racing
        retry inserted it first), the existing job_id wins and is returned."""
        async with self.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT IGNORE INTO ingest_idempotency (user_id, idempotency_key, job_id) "
                    "VALUES (%s, %s, %s)",
                    (user_id, key, job_id),
                )
                inserted = cur.rowcount
            await conn.commit()
        if inserted:
            return job_id
        existing = await self.get_job(user_id, key)
        return existing or job_id


class WebhookDeadLetterRepo(_Repo):
    """Webhook deliveries that exhausted their retry budget (Stage 16 §16.2)."""

    async def add(self, *, user_id: int | None, job_id: str | None, url: str,
                  payload: dict, attempts: int, last_error: str | None) -> int:
        return await self._execute(
            "INSERT INTO webhook_deadletter (user_id, job_id, url, payload, attempts, last_error) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (user_id, job_id, url, _dumps(payload), attempts, last_error),
        )

    async def list_recent(self, limit: int = 50) -> list[dict]:
        rows = await self._fetchall(
            "SELECT * FROM webhook_deadletter ORDER BY id DESC LIMIT %s", (limit,)
        )
        for r in rows:
            r["payload"] = _loads(r["payload"])
        return rows

    async def count(self) -> int:
        row = await self._fetchone("SELECT COUNT(*) AS n FROM webhook_deadletter")
        return int(row["n"])


class MapRepo(_Repo):
    """Read-only access to the seeded map_metadata calibration table."""

    @staticmethod
    def _decode(row: dict | None) -> dict | None:
        if row:
            row["selections"] = _loads(row["selections"])
        return row

    async def get(self, name: str, version: str | None = None) -> dict | None:
        """Resolve a map's calibration by (name, version), Stage 12. With a `version`, return
        that exact calibration; otherwise fall back to the best known: the `live` row, else the
        most recently added. None if the map is unknown (caller renders an unsupported state)."""
        if version is not None:
            row = await self._fetchone(
                "SELECT * FROM map_metadata WHERE name = %s AND version = %s", (name, version)
            )
            if row is not None:
                return self._decode(row)
        return self._decode(await self._fetchone(
            "SELECT * FROM map_metadata WHERE name = %s "
            "ORDER BY (version = 'live') DESC, id DESC LIMIT 1",
            (name,),
        ))

    async def upsert(self, name: str, *, version: str = "live", **fields: Any) -> None:
        """Insert or update a calibration row (admin add/recalibrate — no code change, Stage 12)."""
        fields.setdefault("map_id", 0)   # legacy NOT-NULL column; 0 for new maps
        cols = ["name", "version", *fields.keys()]
        vals = [name, version, *(_dumps(v) if k == "selections" else v
                                 for k, v in fields.items())]
        updates = ", ".join(f"{c} = VALUES({c})" for c in cols if c not in ("name", "version"))
        placeholders = ", ".join(["%s"] * len(cols))
        await self._execute(
            f"INSERT INTO map_metadata ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON DUPLICATE KEY UPDATE {updates or 'name = VALUES(name)'}",
            vals,
        )

    async def list_all(self) -> list[dict]:
        return [self._decode(r) for r in
                await self._fetchall("SELECT * FROM map_metadata ORDER BY name, version")]

    async def list_active_duty(self) -> list[dict]:
        return [self._decode(r) for r in await self._fetchall(
            "SELECT * FROM map_metadata WHERE is_active_duty = 1 ORDER BY name")]

    async def count(self) -> int:
        row = await self._fetchone("SELECT COUNT(*) AS n FROM map_metadata")
        return int(row["n"])
