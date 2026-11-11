"""Owner-only admin API (Stage 3.4) + dashboard.

Auth is a single static admin token (compared in constant time), separate from the public
key auth. Endpoints manage users and their keys (issue/configure/rotate/revoke) and report
current rate-limit usage; a raw key is returned exactly once, at issuance. The dashboard
(GET /admin/) is a single static HTML file that drives these endpoints.
"""
from __future__ import annotations

import hmac
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..config import settings
from ..db import get_pool
from ..redis import get_redis
from ..ingest import queue as ingest_queue
from ..storage.repos import BackfillRepo, DemoRepo, JobRepo, KeyRepo, MapRepo, UserRepo
from ..auth.service import DEFAULT, UNSET, KeyService

router = APIRouter(prefix="/admin", tags=["admin"])

_DASHBOARD = Path(__file__).resolve().parent / "static" / "dashboard.html"

# Public fields of a key (never expose key_hash).
_KEY_FIELDS = ("id", "user_id", "kind", "prefix", "last4", "allowed_origins",
               "rate_per_hour", "status", "created_at", "revoked_at", "expires_at")


def _public_key(row: dict) -> dict:
    return {f: row.get(f) for f in _KEY_FIELDS}


def require_admin(request: Request) -> None:
    """Gate every admin endpoint behind the static admin token."""
    token = ""
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    token = token or request.headers.get("X-Admin-Token", "")
    expected = settings.admin_token
    if not token or not expected or not hmac.compare_digest(token, expected):
        raise HTTPException(401, "admin authentication required")


def _key_service(pool) -> KeyService:
    return KeyService(
        KeyRepo(pool), get_redis(),
        cache_ttl=settings.key_cache_ttl,
        rotation_grace=settings.key_rotation_grace_seconds,
        default_rate=settings.client_default_rate_per_hour,
    )


# --- request models --------------------------------------------------------------------

class CreateUser(BaseModel):
    email: str
    display_name: str | None = None


class IssueKey(BaseModel):
    kind: str = Field(pattern="^(client|server)$")
    allowed_origins: list[str] = []
    rate_per_hour: int | None = None


class PatchKey(BaseModel):
    allowed_origins: list[str] | None = None
    rate_per_hour: int | None = None
    action: str | None = Field(default=None, pattern="^(rotate|revoke)$")


class UpdateUser(BaseModel):
    display_name: str | None = None
    status: str | None = Field(default=None, pattern="^(active|suspended)$")
    tier: str | None = Field(default=None, pattern="^(enterprise|standard|free)$")


# --- endpoints -------------------------------------------------------------------------

@router.post("/users", dependencies=[Depends(require_admin)], status_code=201)
async def create_user(body: CreateUser) -> dict:
    users = UserRepo(await get_pool())
    if await users.get_by_email(body.email):
        raise HTTPException(409, "email already exists")
    uid = await users.create(body.email, body.display_name)
    return {"id": uid, "email": body.email, "display_name": body.display_name}


@router.get("/users", dependencies=[Depends(require_admin)])
async def list_users() -> dict:
    return {"users": await UserRepo(await get_pool()).list()}


@router.patch("/users/{user_id}", dependencies=[Depends(require_admin)])
async def update_user(user_id: int, body: UpdateUser) -> dict:
    pool = await get_pool()
    if await UserRepo(pool).get(user_id) is None:
        raise HTTPException(404, "user not found")
    await UserRepo(pool).update(
        user_id,
        display_name=UNSET if body.display_name is None else body.display_name,
        status=body.status,
        tier=body.tier,
    )
    # A status change flips whether the user's keys authenticate — bust their cache.
    if body.status is not None:
        await _key_service(pool).bust_user(user_id)
    return {"id": user_id, "updated": True}


@router.post("/users/{user_id}/webhook-secret", dependencies=[Depends(require_admin)])
async def issue_webhook_secret(user_id: int) -> dict:
    """Issue or rotate the tenant's webhook HMAC signing secret (Stage 16 §16.2). The raw secret
    is returned exactly once — store it; outbound webhooks are signed with it (see deploy/WEBHOOKS.md)."""
    from ..webhooks import new_secret

    pool = await get_pool()
    if await UserRepo(pool).get(user_id) is None:
        raise HTTPException(404, "user not found")
    secret = new_secret()
    await UserRepo(pool).set_webhook_secret(user_id, secret)
    return {"user_id": user_id, "webhook_secret": secret}


@router.get("/webhooks/deadletter", dependencies=[Depends(require_admin)])
async def webhook_deadletter(limit: int = 50) -> dict:
    """Webhook deliveries that exhausted their retry budget (Stage 16 §16.2) — for replay/visibility."""
    from ..storage.repos import WebhookDeadLetterRepo

    dl = WebhookDeadLetterRepo(await get_pool())
    return {"count": await dl.count(), "deadletter": await dl.list_recent(limit=min(limit, 200))}


@router.get("/users/{user_id}/keys", dependencies=[Depends(require_admin)])
async def list_user_keys(user_id: int) -> dict:
    pool = await get_pool()
    if await UserRepo(pool).get(user_id) is None:
        raise HTTPException(404, "user not found")
    keys = await KeyRepo(pool).list_for_user(user_id)
    return {"keys": [_public_key(k) for k in keys]}


@router.post("/users/{user_id}/keys", dependencies=[Depends(require_admin)], status_code=201)
async def issue_key(user_id: int, body: IssueKey) -> dict:
    pool = await get_pool()
    if await UserRepo(pool).get(user_id) is None:
        raise HTTPException(404, "user not found")
    # None → DEFAULT sentinel so the service applies the per-kind default
    # (client → 100/hr, server → no limit) rather than storing a literal NULL.
    rate = DEFAULT if body.rate_per_hour is None else body.rate_per_hour
    key_id, gen = await _key_service(pool).issue(
        user_id, body.kind, allowed_origins=body.allowed_origins, rate_per_hour=rate
    )
    # Raw key shown exactly once.
    return {"id": key_id, "kind": gen.kind, "prefix": gen.prefix,
            "last4": gen.last4, "key": gen.raw}


@router.patch("/keys/{key_id}", dependencies=[Depends(require_admin)])
async def patch_key(key_id: int, body: PatchKey) -> dict:
    pool = await get_pool()
    svc = _key_service(pool)
    if await KeyRepo(pool).get(key_id) is None:
        raise HTTPException(404, "key not found")

    result: dict = {"id": key_id}
    if body.allowed_origins is not None or body.rate_per_hour is not None:
        await svc.set_attrs(
            key_id,
            allowed_origins=body.allowed_origins,
            rate_per_hour=UNSET if body.rate_per_hour is None else body.rate_per_hour,
        )
        result["updated"] = True
    if body.action == "revoke":
        await svc.revoke(key_id)
        result["revoked"] = True
    elif body.action == "rotate":
        new_id, gen = await svc.rotate(key_id)
        result["rotated_to"] = new_id
        result["key"] = gen.raw  # new raw key, shown once
    return result


@router.get("/usage", dependencies=[Depends(require_admin)])
async def usage() -> dict:
    """Current rate-limit window usage per key, read live from Redis (Stage 04 counters).

    Returns one entry per key: client keys carry a single `used` count; server keys carry a
    per-end-user breakdown plus the total. `reset` is when the current window rolls over.
    """
    pool, redis = await get_pool(), get_redis()
    window = settings.rate_limit_window_seconds
    now = time.time()
    bucket = int(now // window)
    reset = int((bucket + 1) * window)

    out = []
    for k in await KeyRepo(pool).list_all():
        kid = k["id"]
        if k["kind"] == "client":
            used = await redis.get(f"rl:ck:{kid}:{bucket}")
            entry = {"used": int(used or 0), "end_users": []}
        else:
            end_users, total = [], 0
            async for rk in redis.scan_iter(match=f"rl:su:{kid}:*:{bucket}"):
                parts = rk.split(":")
                end_user = ":".join(parts[3:-1])  # tolerate ':' inside the end-user id
                count = int(await redis.get(rk) or 0)
                end_users.append({"end_user": end_user, "used": count})
                total += count
            end_users.sort(key=lambda e: e["used"], reverse=True)
            entry = {"used": total, "end_users": end_users}
        out.append({"key_id": kid, "kind": k["kind"], "status": k["status"],
                    "limit": k["rate_per_hour"], **entry})
    return {"window_seconds": window, "reset": reset, "keys": out}


class UpsertMap(BaseModel):
    name: str
    version: str = "live"
    pos_x: float
    pos_y: float
    scale: float
    rotate: float | None = None
    zoom: float | None = None
    image_path: str | None = None
    display_name: str | None = None
    is_active_duty: bool = False
    selections: list | None = None
    map_id: int = 0


@router.post("/maps", dependencies=[Depends(require_admin)], status_code=201)
async def upsert_map(body: UpsertMap) -> dict:
    """Add or recalibrate a map (Stage 12): one row + a radar upload, no code change. A reworked
    map gets a new `version`; the radar lives on the maps CDN (`image_path`)."""
    fields = body.model_dump(exclude={"name", "version"})
    await MapRepo(await get_pool()).upsert(body.name, version=body.version, **fields)
    return {"name": body.name, "version": body.version, "saved": True}


@router.get("/jobs", dependencies=[Depends(require_admin)])
async def list_jobs(status: str | None = None, limit: int = 50) -> dict:
    """Ingest-job visibility (Stage 08 §8.3): counts by status + the recent jobs (with errors),
    so the owner can see what's queued / parsing / failed and why."""
    jobs = JobRepo(await get_pool())
    return {
        "counts": await jobs.counts_by_status(),
        "jobs": await jobs.list_recent(limit=min(limit, 200), status=status),
    }


class StartBackfill(BaseModel):
    target_payload_version: int
    mode: str = Field(default="cheap", pattern="^(cheap|deep)$")
    demo_ids: list[int] | None = None     # default: all ready demos not already at the target


@router.post("/backfill", dependencies=[Depends(require_admin)], status_code=202)
async def start_backfill(body: StartBackfill) -> dict:
    """Start a reprocessing run (Stage 14): create the run + per-demo state, enqueue a task per
    demo on the worker pool. Cheap = re-derive from parquet; deep = re-parse from raw."""
    pool = await get_pool()
    demos = DemoRepo(pool)
    ids = body.demo_ids
    if ids is None:
        ids = await demos.list_ids_for_backfill(payload_version=body.target_payload_version)
    if not ids:
        return {"run_id": None, "total": 0, "detail": "no demos to backfill"}

    run_id = await BackfillRepo(pool).create_run(body.target_payload_version, body.mode, ids)
    for demo_id in ids:
        await ingest_queue.enqueue_backfill(run_id, demo_id, body.target_payload_version, body.mode)
    return {"run_id": run_id, "total": len(ids), "mode": body.mode}


@router.get("/backfill/{run_id}", dependencies=[Depends(require_admin)])
async def backfill_status(run_id: int) -> dict:
    """Backfill run progress (§14.3): totals, per-state counts, and recent failures."""
    bf = BackfillRepo(await get_pool())
    run = await bf.get_run(run_id)
    if run is None:
        raise HTTPException(404, "backfill run not found")
    return {"run": run, "counts": await bf.counts(run_id), "failures": await bf.failures(run_id)}


@router.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    """The admin dashboard (single static HTML file; it prompts for the token in-page)."""
    return FileResponse(_DASHBOARD)
