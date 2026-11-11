"""Durable, signed webhook delivery as an arq task (Stage 16 §16.2).

The ingest pipeline enqueues a `delivery` dict; this task signs it (per-user HMAC + timestamp +
nonce), POSTs it, and on a non-2xx response **retries with exponential backoff** via arq's
reschedule mechanism until the budget is exhausted, then writes a **dead-letter** row so the event
is never silently lost. Separating delivery from ingest means a slow/failing customer endpoint can't
delay parsing, and a transient outage self-heals.
"""
from __future__ import annotations

import time

import httpx
import orjson
from loguru import logger

from .webhooks import (
    MAX_DELIVERY_ATTEMPTS,
    backoff_seconds,
    new_nonce,
    should_retry,
    signature_headers,
)


async def _post_signed(url: str, payload: dict, secret: str, *, timeout: float = 10.0) -> int:
    """Sign + POST the payload; return the HTTP status (raises only on a transport error)."""
    body = orjson.dumps(payload)
    headers = signature_headers(secret, body, timestamp=int(time.time()), nonce=new_nonce()) \
        if secret else {"Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, content=body, headers=headers)
        return resp.status_code


async def webhook_delivery_task(ctx: dict, delivery: dict) -> str:
    """arq task — deliver one webhook with backoff retry → dead-letter (wired in app/worker.py).

    `delivery` = {url, payload, secret, user_id?, job_id?}. Uses arq's `job_try` for the attempt
    count: raise `Retry(defer=…)` while budget remains, else dead-letter and return.
    """
    from arq.worker import Retry

    attempt = int(ctx.get("job_try", 1))
    url, payload = delivery["url"], delivery["payload"]
    secret = delivery.get("secret") or ""

    try:
        status = await _post_signed(url, payload, secret)
        if 200 <= status < 300:
            return "delivered"
        error = f"http_{status}"
    except Exception as exc:  # noqa: BLE001 — network/timeout → treat as a retryable failure
        error = f"{type(exc).__name__}: {exc}"

    if should_retry(attempt, max_attempts=MAX_DELIVERY_ATTEMPTS):
        delay = backoff_seconds(attempt)
        logger.warning(f"webhook to {url} failed ({error}); retry {attempt + 1} in {delay}s")
        raise Retry(defer=delay)

    # Budget exhausted → dead-letter (never silently dropped).
    from .storage.repos import WebhookDeadLetterRepo

    logger.error(f"webhook to {url} dead-lettered after {attempt} attempts ({error})")
    await WebhookDeadLetterRepo(ctx["pool"]).add(
        user_id=delivery.get("user_id"), job_id=delivery.get("job_id"), url=url,
        payload=payload, attempts=attempt, last_error=error,
    )
    return "dead_lettered"
