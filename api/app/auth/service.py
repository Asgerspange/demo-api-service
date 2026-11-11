"""KeyService — issuance, verification (Redis-cached), rotation, and revocation.

Verification caches the key record in Redis with a short TTL (`key_cache_ttl`) so the hot
auth path avoids a DB round-trip. Mutations that change a key's validity (revoke / rotate /
attr change) bust the cache entry for that key's hash, so a revocation takes effect
immediately rather than after the TTL. Expiry (the rotation grace window) is checked against
the wall clock on every call, so a key that expires mid-TTL is still rejected on time.
"""
from __future__ import annotations

import json
import time
from datetime import timezone
from typing import Any

from ..storage.repos import KeyRepo
from .keys import GeneratedKey, generate_key

# Sentinels: distinguish "use the per-kind default" / "leave unchanged" from an explicit value.
DEFAULT: Any = object()
UNSET: Any = object()

_MISS = "__miss__"  # negative-cache marker for unknown/invalid hashes


class KeyService:
    def __init__(self, repo: KeyRepo, redis, *, cache_ttl: int,
                 rotation_grace: int, default_rate: int) -> None:
        self.repo = repo
        self.redis = redis
        self.cache_ttl = cache_ttl
        self.rotation_grace = rotation_grace
        self.default_rate = default_rate

    # --- lookup / verify ---------------------------------------------------------------

    @staticmethod
    def _cache_key(key_hash: str) -> str:
        return f"key:{key_hash}"

    @staticmethod
    def _to_record(row: dict) -> dict:
        exp = row.get("expires_at")
        exp_ts = exp.replace(tzinfo=timezone.utc).timestamp() if exp else None
        return {
            "id": row["id"], "user_id": row["user_id"], "kind": row["kind"],
            "allowed_origins": row["allowed_origins"],
            "rate_per_hour": row["rate_per_hour"], "expires_ts": exp_ts,
            "user_status": row.get("user_status", "active"),
        }

    async def _lookup(self, key_hash: str) -> dict | None:
        ck = self._cache_key(key_hash)
        cached = await self.redis.get(ck)
        if cached is not None:
            return None if cached == _MISS else json.loads(cached)
        row = await self.repo.get_by_hash(key_hash)
        if row is None:
            await self.redis.set(ck, _MISS, ex=self.cache_ttl)
            return None
        rec = self._to_record(row)
        await self.redis.set(ck, json.dumps(rec), ex=self.cache_ttl)
        return rec

    async def verify(self, key_hash: str) -> dict | None:
        """Return the cached key record if active, owner not suspended, and not past its
        grace expiry; else None."""
        rec = await self._lookup(key_hash)
        if rec is None:
            return None
        if rec.get("user_status", "active") != "active":
            return None
        exp = rec["expires_ts"]
        if exp is not None and exp <= time.time():
            return None
        return rec

    async def _bust(self, key_hash: str) -> None:
        await self.redis.delete(self._cache_key(key_hash))

    async def bust_user(self, user_id: int) -> None:
        """Invalidate the cache for every key a user owns (e.g. after suspend/reactivate)."""
        for k in await self.repo.list_for_user(user_id):
            await self._bust(k["key_hash"])

    # --- mutations ---------------------------------------------------------------------

    async def issue(self, user_id: int, kind: str, *, allowed_origins: list[str] | None = None,
                    rate_per_hour: Any = DEFAULT) -> tuple[int, GeneratedKey]:
        gen = generate_key(kind)
        if kind == "client":
            origins = allowed_origins or []
            rate = self.default_rate if rate_per_hour is DEFAULT else rate_per_hour
        else:
            origins = []  # server keys are backend-only; not origin-locked
            rate = None if rate_per_hour is DEFAULT else rate_per_hour
        key_id = await self.repo.create(
            user_id, kind, gen.prefix, gen.key_hash, gen.last4, origins, rate
        )
        return key_id, gen

    async def revoke(self, key_id: int) -> bool:
        row = await self.repo.get(key_id)
        if row is None:
            return False
        await self.repo.revoke(key_id)
        await self._bust(row["key_hash"])
        return True

    async def rotate(self, key_id: int) -> tuple[int, GeneratedKey] | None:
        """Issue a replacement; the old key stays valid for the grace window, then expires."""
        old = await self.repo.get(key_id)
        if old is None:
            return None
        gen = generate_key(old["kind"])
        new_id = await self.repo.create(
            old["user_id"], old["kind"], gen.prefix, gen.key_hash, gen.last4,
            old["allowed_origins"], old["rate_per_hour"],
        )
        await self.repo.begin_rotation(key_id, self.rotation_grace, new_id)
        await self._bust(old["key_hash"])
        return new_id, gen

    async def set_attrs(self, key_id: int, *, allowed_origins: list[str] | None = None,
                        rate_per_hour: Any = UNSET) -> bool:
        row = await self.repo.get(key_id)
        if row is None:
            return False
        # Only forward rate_per_hour when explicitly provided; otherwise let the repo's
        # own "leave unchanged" default apply (the two layers use distinct sentinels).
        extra = {} if rate_per_hour is UNSET else {"rate_per_hour": rate_per_hour}
        await self.repo.set_attrs(key_id, allowed_origins=allowed_origins, **extra)
        await self._bust(row["key_hash"])
        return True
