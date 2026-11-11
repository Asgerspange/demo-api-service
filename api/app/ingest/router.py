"""Intake API (Stage 5.1) — fast, runs in the API process; never parses inline.

`POST /ingest` validates + authorizes the request, writes an `ingest_jobs` row, enqueues the
arq job, and returns `202 {job_id}` immediately. `GET /ingest/{job_id}` reports status. `path`
intake is debug-only and gated to the admin/owner credential — fetching arbitrary server paths
is dangerous, so customers (key only) are refused with 403.
"""
from __future__ import annotations

import hmac
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..auth.context import AuthContext
from ..auth.dependencies import authenticate, require_server_key
from ..config import settings
from ..db import get_pool
from ..fairness import (
    LANE_ENTERPRISE,
    LANE_FREE,
    LANE_STANDARD,
    lane_for_tier,
    over_capacity,
    queue_depth,
)
from ..redis import get_redis
from ..storage.repos import IdempotencyRepo, JobRepo, UserRepo
from . import queue

router = APIRouter(tags=["ingest"])


# --- request models --------------------------------------------------------------------

class Source(BaseModel):
    type: Literal["url", "path"]
    ref: str


class ExternalRef(BaseModel):
    source: str
    external_id: str


class IngestRequest(BaseModel):
    source: Source
    name: str | None = None
    webhook_url: str | None = None
    refs: list[ExternalRef] = []
    anonymize: bool = False           # replace steamids/names with per-demo aliases (Stage 13)
    force: bool = False               # re-parse in place even if this content is already ready
                                      # (bypasses the sha256 dedup short-circuit; e.g. to backfill
                                      # a demo parsed before a stats change)


def _is_admin(request: Request) -> bool:
    """True if the request carries the static admin/owner token (path-intake gate).

    Both `X-Admin-Token` and a `Bearer` token are accepted — on `/ingest` the Bearer slot
    usually holds the user's API key, so we check each candidate independently rather than
    assuming the admin token is in any one header.
    """
    expected = settings.admin_token
    if not expected:
        return False
    auth = request.headers.get("Authorization", "")
    bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    candidates = [request.headers.get("X-Admin-Token", ""), bearer]
    return any(c and hmac.compare_digest(c, expected) for c in candidates)


# --- endpoints -------------------------------------------------------------------------

@router.post("/ingest", status_code=202)
async def create_ingest(
    body: IngestRequest, request: Request,
    ctx: AuthContext = Depends(require_server_key),   # ingestion is a backend op → server key only
) -> dict:
    # `path` intake (debug) is admin/owner-only; a server key alone is refused.
    if body.source.type == "path" and not _is_admin(request):
        raise HTTPException(403, "path intake is restricted to the admin/owner (debug only)")

    pool = await get_pool()
    jobs = JobRepo(pool)

    # Idempotency (Stage 16 §16.2): a retry with the same key returns the SAME job, never a
    # duplicate parse. Scoped per tenant so keys can't collide across users.
    idem_key = request.headers.get("Idempotency-Key")
    idem = IdempotencyRepo(pool)
    if idem_key:
        existing_id = await idem.get_job(ctx.user_id, idem_key)
        if existing_id:
            existing = await jobs.get(existing_id)
            return {"job_id": existing_id,
                    "status": (existing or {}).get("status", "queued"), "idempotent": True}

    # Backpressure (§16.1): shed new work above the queue-depth ceiling rather than growing the
    # queue without bound — a clear, retryable signal instead of silent latency.
    ceiling = settings.ingest_queue_depth_ceiling
    if ceiling > 0:
        depth = await queue_depth(get_redis(), LANE_ENTERPRISE, LANE_STANDARD, LANE_FREE)
        if over_capacity(depth, ceiling):
            raise HTTPException(
                429, "ingestion queue is at capacity; retry shortly",
                headers={"Retry-After": str(settings.ingest_defer_seconds)})

    # Route to the tenant's tier lane (enterprise > standard > free); §16.1.
    tier = (await UserRepo(pool).get(ctx.user_id) or {}).get("tier")
    lane = lane_for_tier(tier)

    job_id = str(uuid.uuid4())
    await jobs.create(
        job_id, body.source.type, body.source.ref,
        user_id=ctx.user_id, status="queued", webhook_url=body.webhook_url,
    )
    # Stash the request (name + refs) on the job so the worker can read it back.
    await jobs.update(job_id, progress={
        "request": {"name": body.name, "refs": [r.model_dump() for r in body.refs],
                    "anonymize": body.anonymize, "force": body.force},
        "stage": "queued",
    })

    # Bind the idempotency key now that the job row exists (FK). On a concurrent race the first
    # writer wins; if our job lost, drop the duplicate and return the winner instead.
    if idem_key:
        winner = await idem.put(ctx.user_id, idem_key, job_id)
        if winner != job_id:
            await jobs.delete(job_id)
            won = await jobs.get(winner)
            return {"job_id": winner, "status": (won or {}).get("status", "queued"),
                    "idempotent": True}

    await queue.enqueue_ingest(job_id, lane=lane)
    return {"job_id": job_id, "status": "queued", "lane": lane}


@router.get("/ingest/{job_id}")
async def get_ingest(job_id: str, ctx: AuthContext = Depends(authenticate)) -> dict:
    job = await JobRepo(await get_pool()).get(job_id)
    # 404 for both missing and not-owned, so a job id can't be probed across tenants.
    if job is None or job["user_id"] != ctx.user_id:
        raise HTTPException(404, "ingest job not found")
    return {
        "job_id": job_id,
        "status": job["status"],
        "demo_id": job["demo_id"],
        "progress": job["progress"],
        "error": job["error"],
    }
