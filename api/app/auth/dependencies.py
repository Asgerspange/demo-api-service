"""The FastAPI auth dependency (Stage 3.3).

`authenticate()` resolves an incoming request to an AuthContext:
- client key (Authorization: Bearer / X-Client-Key) → enforce the origin allowlist (403);
- server key (X-Server-Key) → reject if it arrived from a browser (Origin present → 400),
  require X-End-User (→ 400), attribute the owner-set per-user limit.
Invalid/expired/unknown key → 401. The context feeds routers and the rate limiter (Stage 04).
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from ..config import settings
from ..db import get_pool
from ..redis import get_redis
from ..storage.repos import KeyRepo
from .context import AuthContext
from .keys import hash_key, kind_from_key
from .origins import host_from_origin, origin_allowed
from .service import KeyService


async def get_key_service() -> KeyService:
    """Single injection point for the key service (overridden in tests)."""
    pool = await get_pool()
    return KeyService(
        KeyRepo(pool), get_redis(),
        cache_ttl=settings.key_cache_ttl,
        rotation_grace=settings.key_rotation_grace_seconds,
        default_rate=settings.client_default_rate_per_hour,
    )


def _extract_key(request: Request) -> str | None:
    """Pull the presented key. X-Server-Key wins (explicit backend use), then Bearer/X-Client-Key."""
    if sk := request.headers.get("X-Server-Key"):
        return sk
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("X-Client-Key")


async def authenticate(
    request: Request, svc: KeyService = Depends(get_key_service)
) -> AuthContext:
    raw = _extract_key(request)
    if not raw:
        raise HTTPException(401, "missing API key")
    kind = kind_from_key(raw)
    if kind is None:
        raise HTTPException(401, "invalid API key")

    # A server key must never be accepted on a request that came straight from a browser.
    if kind == "server" and request.headers.get("Origin"):
        raise HTTPException(400, "server keys must be used from your backend, not a browser")

    rec = await svc.verify(hash_key(raw))
    if rec is None or rec["kind"] != kind:
        raise HTTPException(401, "invalid or expired API key")

    if kind == "client":
        origin = request.headers.get("Origin") or request.headers.get("Referer")
        if not origin_allowed(host_from_origin(origin), rec["allowed_origins"]):
            raise HTTPException(403, "origin not allowed for this client key")
        return AuthContext(key_id=rec["id"], user_id=rec["user_id"], kind="client",
                           rate_per_hour=rec["rate_per_hour"])

    end_user = request.headers.get("X-End-User")
    if not end_user:
        raise HTTPException(400, "X-End-User header required for server keys")
    return AuthContext(key_id=rec["id"], user_id=rec["user_id"], kind="server",
                       rate_per_hour=rec["rate_per_hour"], end_user=end_user)


async def require_server_key(ctx: AuthContext = Depends(authenticate)) -> AuthContext:
    """Gate write/destructive operations (ingest, delete) to the SECRET server key.

    Client keys are public (embedded in the viewer on customer sites) and only origin-locked as
    defense-in-depth, so they must never be able to mutate or delete data — only read (Stage 13).
    """
    if ctx.kind != "server":
        raise HTTPException(
            403, "this operation requires a server (secret) key, not a public client key"
        )
    return ctx
