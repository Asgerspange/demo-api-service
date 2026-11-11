"""Origin allowlisting for client keys (Stage 3.1).

A public client key is safe to embed only if it works *only* from the sites the owner
allowlisted. We match the request's `Origin` (or `Referer`) host against the key's
`allowed_origins`, supporting a single leading `*.` wildcard (`*.example.com` matches
`app.example.com` and bare `example.com`, but not `evil-example.com`).
"""
from __future__ import annotations

from urllib.parse import urlsplit


def host_from_origin(origin: str | None) -> str | None:
    """Extract a lowercase hostname from an Origin/Referer header value."""
    if not origin:
        return None
    # Origin is scheme://host[:port]; Referer may carry a path. urlsplit handles both.
    parts = urlsplit(origin if "//" in origin else f"//{origin}")
    return parts.hostname.lower() if parts.hostname else None


def _matches(host: str, pattern: str) -> bool:
    # Normalize the allowlist entry to a bare host, keeping any leading `*.` wildcard:
    # strip scheme (`https://`), then any port/path. (urlsplit chokes on `*`, so do it
    # by hand.)
    pattern = pattern.strip().lower()
    if "//" in pattern:
        pattern = pattern.split("//", 1)[1]
    pattern = pattern.split("/", 1)[0].split(":", 1)[0]
    if pattern.startswith("*."):
        base = pattern[2:]
        return host == base or host.endswith("." + base)
    return host == pattern


def origin_allowed(host: str | None, allowed: list[str]) -> bool:
    """True if `host` matches any allowlist entry (wildcards supported)."""
    if not host:
        return False
    return any(_matches(host, p) for p in allowed)
