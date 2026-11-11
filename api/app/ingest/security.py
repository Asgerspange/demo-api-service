"""SSRF guard for URL ingestion (Stage 5.3, gap #4).

A download URL is attacker-influenced, so before we fetch it we:
- require an http/https scheme,
- resolve the host and reject any answer in a private/loopback/link-local/CGNAT/reserved
  range or the cloud metadata address (169.254.169.254 is link-local, covered),
- (the caller disables redirects so a 30x can't bounce us onto an internal host after the
  check — see acquire.download).

`ipaddress` classifies most dangerous ranges via `is_private`/`is_loopback`/`is_link_local`/
`is_reserved`/`is_multicast`/`is_unspecified`; CGNAT `100.64.0.0/10` is *not* flagged by
`is_private` on some Python versions, so we block it explicitly.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from .errors import SSRFError

# Shared address space (RFC 6598) — not covered by is_private everywhere.
_CGNAT4 = ipaddress.ip_network("100.64.0.0/10")


def ip_is_blocked(ip: str | ipaddress._BaseAddress) -> bool:
    """True if `ip` is in a range we must never fetch from."""
    addr = ip if isinstance(ip, ipaddress._BaseAddress) else ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped  # unwrap ::ffff:10.0.0.1 etc.
    if (addr.is_private or addr.is_loopback or addr.is_link_local
            or addr.is_multicast or addr.is_reserved or addr.is_unspecified):
        return True
    return addr.version == 4 and addr in _CGNAT4


def resolve_host(host: str) -> list[str]:
    """Resolve a hostname to all its IPs (raises SSRFError if it can't be resolved)."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SSRFError(f"could not resolve host: {host}") from exc
    return sorted({info[4][0] for info in infos})


def assert_url_allowed(url: str) -> list[str]:
    """Validate a download URL against the SSRF policy; return its resolved IPs.

    Raises SSRFError for a non-http(s) scheme, a missing host, an IP literal in a blocked
    range, or a hostname that resolves (wholly or partly) into a blocked range. We reject if
    *any* resolved address is blocked — a host that returns one public and one private answer
    is treated as hostile.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"unsupported URL scheme: {parsed.scheme or '(none)'}")
    host = parsed.hostname
    if not host:
        raise SSRFError("URL has no host")

    # IP literal: classify directly (no DNS).
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if ip_is_blocked(literal):
            raise SSRFError(f"URL host is a blocked address: {host}")
        return [str(literal)]

    ips = resolve_host(host)
    blocked = [ip for ip in ips if ip_is_blocked(ip)]
    if blocked:
        raise SSRFError(f"host {host} resolves to a blocked address: {', '.join(blocked)}")
    return ips
