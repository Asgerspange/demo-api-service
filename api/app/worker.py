"""arq worker entrypoint.

Run with:  arq app.worker.WorkerSettings

Acquires the shared DB pool + object stores on startup and exposes them on the arq `ctx`, so
the ingestion task (`app.ingest.pipeline.ingest_demo`) reuses one pool/connection set per
worker process. Concurrency (`max_jobs`) bounds parallel parses per worker.
"""
from arq.connections import RedisSettings

from .backfill import backfill_demo_task
from .config import settings
from .db import close_pool, get_pool
from .fairness import LANES_BY_PRIORITY
from .ingest.pipeline import ingest_demo
from .ingest.queue import close_arq
from .storage.object_store import archive_store, object_store
from .webhook_delivery import webhook_delivery_task


async def ping(ctx) -> str:
    """Lightweight liveness task (used by smoke checks)."""
    return "pong"


async def startup(ctx) -> None:
    ctx["pool"] = await get_pool()
    ctx["store"] = object_store()       # demos zone: per-round payloads + canonical.zip
    ctx["archive"] = archive_store()    # cold: raw .dem


async def shutdown(ctx) -> None:
    await close_pool()
    await close_arq()


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    functions = [ingest_demo, backfill_demo_task, webhook_delivery_task, ping]
    on_startup = startup
    on_shutdown = shutdown
    # Bound concurrent CPU-heavy parses per worker process.
    max_jobs = 4
    # Which priority lane this worker pool drains (Stage 16 §16.1). Defaults to the STANDARD lane
    # (arq's default queue), so the baseline single worker works with no config. Run additional
    # pools for the other lanes with `WORKER_QUEUE=arq:queue:enterprise` etc. — see deploy/README.md.
    queue_name = settings.worker_queue or LANES_BY_PRIORITY[1]  # LANE_STANDARD == "arq:queue"
