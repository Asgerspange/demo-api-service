"""Enqueue ingestion jobs onto the arq queue (the API never parses inline, Stage 5.1).

A single process-wide arq Redis pool is created lazily and reused. The router calls
`enqueue_ingest(job_id)`; the worker (`app/worker.py`) consumes `ingest_demo`. Tests
monkeypatch `enqueue_ingest` so the intake API can be driven without a live Redis/worker.
"""
from __future__ import annotations

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from ..config import settings
from ..fairness import LANE_BACKFILL, LANE_STANDARD

INGEST_TASK = "ingest_demo"
WEBHOOK_TASK = "webhook_delivery_task"

_arq: ArqRedis | None = None


async def get_arq() -> ArqRedis:
    global _arq
    if _arq is None:
        _arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _arq


async def close_arq() -> None:
    global _arq
    if _arq is not None:
        await _arq.aclose()
        _arq = None


async def enqueue_ingest(job_id: str, *, lane: str = LANE_STANDARD) -> None:
    """Enqueue an ingestion job onto its tenant-tier priority lane (Stage 16 §16.1).

    arq's `_job_id` makes a duplicate enqueue a no-op; `_queue_name` routes to the lane a worker
    pool of the matching tier consumes.
    """
    arq = await get_arq()
    await arq.enqueue_job(INGEST_TASK, job_id, _job_id=f"ingest:{job_id}", _queue_name=lane)


async def enqueue_backfill(run_id: int, demo_id: int, target_pv: int, mode: str) -> None:
    """Enqueue one demo of a backfill run on the strictly-lowest backfill lane (Stage 14/16).
    `_job_id` dedupes (run, demo) re-enqueues."""
    arq = await get_arq()
    await arq.enqueue_job("backfill_demo_task", run_id, demo_id, target_pv, mode,
                          _job_id=f"backfill:{run_id}:{demo_id}", _queue_name=LANE_BACKFILL)


async def enqueue_webhook(delivery: dict, *, defer_seconds: int = 0) -> None:
    """Enqueue (or re-enqueue with backoff) a signed webhook delivery (Stage 16 §16.2)."""
    arq = await get_arq()
    await arq.enqueue_job(WEBHOOK_TASK, delivery, _defer_by=defer_seconds)
