"""Acquire raw bytes for ingestion (Stage 5.2 step 1).

`url`  → stream-download with httpx under an SSRF guard, a hard byte cap, and a hard timeout;
         redirects are **disabled** so a 30x cannot bounce us onto an internal host *after*
         the pre-flight DNS check (the simplest sound defense per Stage 5.3).
`path` → read a local file (admin/debug only; the router enforces that).

Bytes are returned in memory — a CS2 demo is <= a few hundred MB and we cap it; the worker
writes them to a temp file for awpy and deletes it in a `finally` (Stage 5.3 temp hygiene).
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx

from .errors import DownloadError, TooLargeError
from .security import assert_url_allowed


def _pin_to_ip(url: str, ip: str) -> tuple[str, dict, dict]:
    """Rewrite the URL to connect to a specific (already-validated) IP, preserving the original
    Host header and TLS SNI/cert-verification hostname. Returns (pinned_url, headers, extensions).

    This closes the DNS-rebinding TOCTOU: we dial the exact IP we vetted instead of letting httpx
    re-resolve the hostname at connect time (when an attacker could have flipped it to 10.x /
    169.254.169.254 / 127.0.0.1).
    """
    parsed = urlparse(url)
    host = parsed.hostname
    netloc = f"[{ip}]" if ":" in ip else ip            # bracket IPv6
    if parsed.port:
        netloc += f":{parsed.port}"
    pinned_url = parsed._replace(netloc=netloc).geturl()
    host_header = host + (f":{parsed.port}" if parsed.port else "")
    return pinned_url, {"Host": host_header}, {"sni_hostname": host}


async def download(
    url: str,
    *,
    max_bytes: int,
    timeout: float,
    client: httpx.AsyncClient | None = None,
) -> bytes:
    """
    Securely download a URL with:
    - SSRF protection (DNS resolution + IP validation)
    - No redirects
    - Byte cap
    - Timeout
    - CDN compatibility (no IP pinning)
    """

    # 🔒 Validate URL and resolve DNS
    ips = assert_url_allowed(url)

    # Optional but recommended: prefer IPv4 to avoid Hetzner IPv6 issues
    ipv4s = [ip for ip in ips if ":" not in ip]
    if ipv4s:
        resolved_ip = ipv4s[0]
    else:
        resolved_ip = ips[0]

    # ⚠️ IMPORTANT: we DO NOT pin to IP anymore
    # We only validate that DNS resolution is safe

    owns = client is None
    client = client or httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
    )

    try:
        async with client.stream("GET", url) as resp:
            if resp.is_redirect:
                raise DownloadError(
                    f"refusing to follow redirect ({resp.status_code}) to "
                    f"{resp.headers.get('location', '?')}"
                )

            if resp.status_code >= 400:
                raise DownloadError(f"download failed: HTTP {resp.status_code}")

            declared = resp.headers.get("content-length")
            if declared and declared.isdigit():
                if int(declared) > max_bytes:
                    raise TooLargeError(
                        f"source declares {declared} bytes (> {max_bytes} cap)"
                    )

            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    raise TooLargeError(
                        f"download exceeded the {max_bytes} byte cap"
                    )

            return bytes(buf)

    except httpx.HTTPError as exc:
        raise DownloadError(f"download failed: {exc}") from exc

    finally:
        if owns:
            await client.aclose()

def read_path(path: str, *, max_bytes: int) -> bytes:
    """Read a local `.dem`/archive from disk (debug/admin intake)."""
    if not os.path.isfile(path):
        raise DownloadError(f"local path not found: {path}")
    size = os.path.getsize(path)
    if size > max_bytes:
        raise TooLargeError(f"local file is {size} bytes (> {max_bytes} cap)")
    with open(path, "rb") as fp:
        return fp.read()
