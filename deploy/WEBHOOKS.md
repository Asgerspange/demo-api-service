# Webhooks (Stage 16 §16.2)

The API calls your `webhook_url` when an ingest job reaches a terminal state. Deliveries are
**HMAC-signed**, carry a **timestamp + nonce** for replay protection, and are **retried with
exponential backoff** to a **dead-letter** if your endpoint stays unavailable.

## Events

```json
{ "event": "demo.ready",  "job_id": "…", "demo_id": 123, "status": "ready" }
{ "event": "demo.failed", "job_id": "…", "demo_id": null, "status": "failed" }
```

## Signature scheme

Each request carries:

```
X-Demoviewer-Timestamp: <unix seconds>
X-Demoviewer-Nonce:     <hex>
X-Demoviewer-Signature: v1=<hex hmac-sha256>
Content-Type:           application/json
```

The signature is `HMAC_SHA256(secret, "{timestamp}.{nonce}.{raw_body}")`, hex-encoded. The
`secret` is your **per-tenant webhook secret**, issued to you by the operator (shown once). If you
need it (re)issued, ask the operator — it's managed owner-side, not over the public API.

## Verifying (reference)

1. Reject if `abs(now - timestamp)` exceeds your tolerance (we recommend **300 s**).
2. Reject if you have already seen `nonce` within that window (store recent nonces) — replay defense.
3. Recompute `HMAC_SHA256(secret, "{timestamp}.{nonce}.{body}")` and **constant-time** compare to the
   `v1=` value. Reject on mismatch.

```python
import hmac, hashlib, time
def verify(secret, body, ts, nonce, sig_header, tolerance=300):
    if abs(int(time.time()) - int(ts)) > tolerance:
        return False
    v1 = dict(p.split("=", 1) for p in sig_header.split(",")).get("v1")
    expected = hmac.new(secret.encode(), f"{ts}.{nonce}.".encode() + body, hashlib.sha256).hexdigest()
    return v1 is not None and hmac.compare_digest(expected, v1)
```

(This mirrors `app/webhooks.py::verify_signature`, the harness used by our own tests.)

## Delivery, retries & dead-letter

- A non-2xx response (or a connection error) is retried with backoff **1s, 2s, 4s, 8s, 16s**
  (capped at 300s) for up to **5 attempts** total.
- After the budget is exhausted the event is recorded in a dead-letter store the operator can
  inspect / replay — **never silently dropped**.
- Return `2xx` quickly; do slow work async. A slow endpoint only delays *your* webhook, never our
  ingest (delivery runs on a separate worker task).

## Idempotency on your side

Retries mean you may receive the same event more than once. De-duplicate on `(job_id, event)` —
and on **your** POST /ingest, send an `Idempotency-Key` header so a retried submission returns the
same `job_id` instead of creating a duplicate parse.
