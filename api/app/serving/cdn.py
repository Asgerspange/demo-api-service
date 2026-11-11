"""bunny.net Token Authentication — signed, short-TTL payload URLs (Stage 13 §13.1).

Per-round payloads are served straight from the CDN edge (so reads never hit the origin), which
means the CDN must reject anyone without a valid token — otherwise the guessable keys
`{id}/v{pv}/round-i.bin` would let anyone scrape a customer's library. The API mints a **directory
token** for a demo's payload prefix *after* auth + origin-lock + rate-limit + bandwidth; the
viewer appends it to each round URL. Tokens are scoped (one demo prefix), short-lived, and not
reusable across demos.

The signing follows bunny's documented URL-token algorithm (sha256 over key+path+expires, URL-safe
base64). NOTE: validate the exact token format against bunny's current Token Authentication docs
when enabling it on the pull zone — the CDN-side 403/200 behavior can't be unit-tested here.
"""
from __future__ import annotations

import base64
import hashlib
import time

from ..config import settings


def _b64url(raw: bytes) -> str:
    return base64.b64encode(raw).decode().replace("\n", "").replace("+", "-").replace("/", "_").replace("=", "")


def sign_directory(token_path: str, expires: int, security_key: str) -> str:
    """Sign a directory prefix (e.g. `/42/v1/`) so the token covers every file beneath it."""
    hashable = f"{security_key}{token_path}{expires}"
    return _b64url(hashlib.sha256(hashable.encode()).digest())


def demo_cdn_token(demo_id: int, payload_version: int, *, cdn_host: str | None = None,
                   security_key: str | None = None, ttl: int | None = None,
                   now: int | None = None) -> dict | None:
    """Build the per-demo CDN token block for the serving metadata, or None if not configured.

    The viewer fetches `{base}/{demo_id}/v{pv}/round-{i}.bin?token=…&expires=…&token_path=…`.
    """
    cdn_host = cdn_host if cdn_host is not None else settings.bunny_demos_cdn_host
    security_key = security_key if security_key is not None else settings.bunny_demos_token_key
    if not cdn_host or not security_key:
        return None
    ttl = ttl if ttl is not None else settings.cdn_token_ttl
    expires = (now if now is not None else int(time.time())) + ttl
    token_path = f"/{demo_id}/v{payload_version}/"
    return {
        "base": f"https://{cdn_host}",
        "token": sign_directory(token_path, expires, security_key),
        "expires": expires,
        "token_path": token_path,
    }
