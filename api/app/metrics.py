"""Prometheus metrics (Stage 08 §8.3).

Exposes request rate/latency, 429 rate, ingest queue depth, parse time, and ingest outcomes
at `GET /metrics` so a Prometheus scrape can drive the dashboards (queue depth, parse time,
429 rate). CDN hit ratio is a bunny-side metric (read from the bunny dashboard/API), not
something the origin can observe — the rest live here.

Counters/histograms are updated inline (middleware, rate limiter, worker); gauges that reflect
external state (queue depth, job-status counts) are sampled at scrape time in the endpoint.
"""
from __future__ import annotations

import time

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["method", "route"]
)
RATE_LIMITED = Counter(
    "rate_limited_total", "Requests rejected by the rate limiter", ["kind"]
)
INGEST_OUTCOMES = Counter(
    "ingest_jobs_outcome_total", "Ingest job terminal outcomes", ["outcome"]  # ready|failed|deduped
)
PARSE_SECONDS = Histogram(
    "ingest_parse_seconds", "awpy parse wall time",
    buckets=(1, 5, 10, 20, 30, 60, 120, 300, 600, 1800),
)
QUEUE_DEPTH = Gauge("ingest_queue_depth", "arq queued job count")
JOBS_BY_STATUS = Gauge("ingest_jobs_by_status", "ingest_jobs rows by status", ["status"])


async def request_metrics_middleware(request, call_next):
    """Time every request and count it by route template + status (low-cardinality labels)."""
    start = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    label = getattr(route, "path", None) or "unmatched"
    method = request.method
    HTTP_LATENCY.labels(method, label).observe(time.perf_counter() - start)
    HTTP_REQUESTS.labels(method, label, str(response.status_code)).inc()
    return response


async def render_metrics(pool, redis) -> tuple[bytes, str]:
    """Sample the external-state gauges, then render the exposition format."""
    try:
        # arq stores queued job ids in a sorted set named 'arq:queue'.
        QUEUE_DEPTH.set(await redis.zcard("arq:queue"))
    except Exception:  # noqa: BLE001 — metrics must never fail the scrape
        pass
    try:
        from .storage.repos import JobRepo
        counts = await JobRepo(pool).counts_by_status()
        for status in ("queued", "downloading", "parsing", "ready", "failed"):
            JOBS_BY_STATUS.labels(status).set(counts.get(status, 0))
    except Exception:  # noqa: BLE001
        pass
    return generate_latest(), CONTENT_TYPE_LATEST
