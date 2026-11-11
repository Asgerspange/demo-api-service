"""API key generation, hashing, and parsing (Stage 3.1).

Stripe-style keys: `pk_live_<base62(32 bytes)>` (client) / `sk_live_<…>` (server). We store
only a sha256 hash of the full key (indexable in `api_keys.key_hash CHAR(64)`), the display
`prefix`, and `last4`. The raw key is shown exactly once, at creation. Verification hashes
the presented key and looks it up — the raw secret is never persisted.

sha256 (not argon2) is deliberate: the secret is 32 bytes of CSPRNG entropy, so it is not
brute-forceable from the hash, and a fast deterministic hash is what lets us index + cache
the lookup. (argon2 is for low-entropy human passwords.)
"""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

CLIENT_PREFIX = "pk_live"
SERVER_PREFIX = "sk_live"
_KIND_BY_PREFIX = {CLIENT_PREFIX: "client", SERVER_PREFIX: "server"}
_PREFIX_BY_KIND = {"client": CLIENT_PREFIX, "server": SERVER_PREFIX}

_SECRET_BYTES = 32
_BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def _base62(raw: bytes) -> str:
    n = int.from_bytes(raw, "big")
    if n == 0:
        return "0"
    out = []
    while n:
        n, rem = divmod(n, 62)
        out.append(_BASE62[rem])
    return "".join(reversed(out))


@dataclass(frozen=True)
class GeneratedKey:
    raw: str          # shown to the owner once
    kind: str         # 'client' | 'server'
    prefix: str       # 'pk_live' | 'sk_live'
    key_hash: str     # sha256 hex — what we store
    last4: str


def hash_key(raw: str) -> str:
    """sha256 hex of the full presented key — the stored/looked-up value."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_key(kind: str) -> GeneratedKey:
    """Mint a new key of `kind` ('client' | 'server')."""
    try:
        prefix = _PREFIX_BY_KIND[kind]
    except KeyError:
        raise ValueError(f"unknown key kind: {kind!r}")
    secret = _base62(secrets.token_bytes(_SECRET_BYTES))
    raw = f"{prefix}_{secret}"
    return GeneratedKey(raw=raw, kind=kind, prefix=prefix,
                        key_hash=hash_key(raw), last4=raw[-4:])


def kind_from_key(raw: str) -> str | None:
    """Classify a presented key by its prefix, or None if it isn't one of ours."""
    parts = raw.split("_", 2)
    if len(parts) < 3:
        return None
    return _KIND_BY_PREFIX.get(f"{parts[0]}_{parts[1]}")
