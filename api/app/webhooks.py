"""Webhook security & delivery (Stage 16 §16.2).

Outbound webhooks (ingest `ready`/`failed`) are **HMAC-signed** with a per-user secret, carry a
timestamp + nonce for replay protection, and are delivered with **exponential backoff retry** to a
**dead-letter** after the budget is exhausted. The signature scheme is documented for customers in
`deploy/WEBHOOKS.md` and mirrored by `verify_signature` here (used by the tests and shippable as a
reference verifier).

Signature scheme
----------------
The signed string is `"{timestamp}.{nonce}.{body}"` where `body` is the exact JSON bytes sent.

    X-Demoviewer-Timestamp: <unix seconds>
    X-Demoviewer-Nonce:     <hex>
    X-Demoviewer-Signature: v1=<hex hmac-sha256>

Verify: recompute `HMAC_SHA256(secret, "{ts}.{nonce}.{body}")`, constant-time compare to `v1`,
reject if `|now - ts|` exceeds the tolerance (default 5 min) or the nonce was already seen.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

SIGNATURE_VERSION = "v1"
DEFAULT_TOLERANCE_SECONDS = 300

# Retry budget for delivery (§16.2): attempts 1..MAX, exponential backoff, then dead-letter.
MAX_DELIVERY_ATTEMPTS = 5


def new_secret() -> str:
    """A fresh per-user webhook signing secret (hex, 256-bit)."""
    return secrets.token_hex(32)


def new_nonce() -> str:
    return secrets.token_hex(16)


def _signed_string(timestamp: int, nonce: str, body: bytes) -> bytes:
    return f"{timestamp}.{nonce}.".encode() + body


def sign(secret: str, body: bytes, *, timestamp: int, nonce: str) -> str:
    """Compute the `v1` HMAC-SHA256 signature over `{ts}.{nonce}.{body}`."""
    mac = hmac.new(secret.encode(), _signed_string(timestamp, nonce, body), hashlib.sha256)
    return mac.hexdigest()


def signature_headers(secret: str, body: bytes, *, timestamp: int,
                      nonce: str | None = None) -> dict[str, str]:
    """Build the full set of signing headers for a request body."""
    nonce = nonce or new_nonce()
    sig = sign(secret, body, timestamp=timestamp, nonce=nonce)
    return {
        "X-Demoviewer-Timestamp": str(timestamp),
        "X-Demoviewer-Nonce": nonce,
        "X-Demoviewer-Signature": f"{SIGNATURE_VERSION}={sig}",
        "Content-Type": "application/json",
    }


def parse_signature(header: str) -> str | None:
    """Extract the `v1` hex from an `X-Demoviewer-Signature` header (`v1=<hex>`)."""
    for part in (header or "").split(","):
        k, _, v = part.strip().partition("=")
        if k == SIGNATURE_VERSION:
            return v
    return None


def verify_signature(secret: str, body: bytes, *, timestamp: int, nonce: str,
                     signature_header: str, now: int,
                     tolerance: int = DEFAULT_TOLERANCE_SECONDS) -> bool:
    """Constant-time verify + timestamp-tolerance check (the customer-side reference, also our test).

    Replay protection's *nonce-already-seen* check is the caller's responsibility (store nonces seen
    within the tolerance window); this verifies authenticity + freshness.
    """
    presented = parse_signature(signature_header)
    if not presented:
        return False
    if abs(now - int(timestamp)) > tolerance:
        return False
    expected = sign(secret, body, timestamp=timestamp, nonce=nonce)
    return hmac.compare_digest(expected, presented)


# --- delivery policy (pure, testable) --------------------------------------------------

def backoff_seconds(attempt: int) -> int:
    """Exponential backoff for delivery attempt `attempt` (1-based): 1, 2, 4, 8, 16 … capped 300s."""
    return min(2 ** max(0, attempt - 1), 300)


def should_retry(attempt: int, *, max_attempts: int = MAX_DELIVERY_ATTEMPTS) -> bool:
    """True while there's retry budget left after a failed `attempt` (1-based)."""
    return attempt < max_attempts
