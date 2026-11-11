"""Phase 04 — proxy contract.

A real transparent proxy (Starlette) forwards `/cs/v1/**` to the owner ASGI app, injecting
`X-Server-Key` + `X-End-User` and passing status/headers/body straight back — exactly what
the shipped `viewer/examples/proxy.php` and `proxy.js` do. We assert the owner side of the
contract and that the proxy is transparent: identity injection, per-end-user isolation,
status + response-header passthrough (incl. `X-RateLimit-*`). Full binary/gzip + cache-header
passthrough over real serving routes is exercised in Stage 06.
"""
import contextlib

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import Response as StarletteResponse
from starlette.routing import Route

from app.main import app as owner_app

pytestmark = pytest.mark.integration

# Hop-by-hop / length headers a transparent proxy must not copy verbatim (the body is re-framed).
_HOP = {"content-length", "content-encoding", "transfer-encoding", "connection", "keep-alive"}


@contextlib.asynccontextmanager
async def proxy_client(server_key: str):
    """An httpx client pointed at a transparent proxy that forwards to the owner app."""
    owner = httpx.AsyncClient(transport=httpx.ASGITransport(app=owner_app), base_url="http://owner")

    async def handler(request):
        upstream_path = request.url.path[len("/cs"):]            # strip only the /cs prefix
        end_user = request.headers.get("X-Test-User", "anon")    # a backend would derive this
        r = await owner.get(
            upstream_path, params=dict(request.query_params),
            headers={"X-Server-Key": server_key, "X-End-User": end_user},
        )
        headers = {k: v for k, v in r.headers.items() if k.lower() not in _HOP}
        return StarletteResponse(content=r.content, status_code=r.status_code, headers=headers)

    proxy_app = Starlette(routes=[Route("/cs/{path:path}", handler, methods=["GET"])])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=proxy_app),
                                 base_url="http://customer.com") as client:
        try:
            yield client
        finally:
            await owner.aclose()


async def _issue_server_key(api, admin_headers, email, **body) -> tuple[int, str]:
    uid = (await api.post("/admin/users", json={"email": email},
                          headers=admin_headers)).json()["id"]
    raw = (await api.post(f"/admin/users/{uid}/keys",
                          json={"kind": "server", **body}, headers=admin_headers)).json()["key"]
    return uid, raw


async def test_proxy_forwards_and_injects_server_identity(api, admin_headers):
    uid, key = await _issue_server_key(api, admin_headers, "p@x.com")
    async with proxy_client(key) as proxy:
        # The viewer sends NO secret — just hits the customer proxy base.
        r = await proxy.get("/cs/v1/whoami", headers={"X-Test-User": "user-7"})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "server"        # the proxy's X-Server-Key was applied
    assert body["end_user"] == "user-7"    # the proxy's X-End-User was applied
    assert body["user_id"] == uid


async def test_proxy_passes_through_response_headers(api, admin_headers):
    _, key = await _issue_server_key(api, admin_headers, "h@x.com", rate_per_hour=5)
    async with proxy_client(key) as proxy:
        r = await proxy.get("/cs/v1/whoami", headers={"X-Test-User": "u1"})
    assert r.status_code == 200
    # The owner's rate-limit headers survive the proxy unchanged (same mechanism that
    # carries Cache-Control/ETag for cacheable payloads).
    assert r.headers["X-RateLimit-Limit"] == "5"
    assert r.headers["X-RateLimit-Remaining"] == "4"


async def test_proxy_passes_through_error_status(api, admin_headers):
    # An invalid server key → owner 401 → the proxy conveys the same status, not its own.
    async with proxy_client("sk_live_invalidkey") as proxy:
        r = await proxy.get("/cs/v1/whoami", headers={"X-Test-User": "u1"})
    assert r.status_code == 401


async def test_proxy_isolates_per_end_user(api, admin_headers):
    _, key = await _issue_server_key(api, admin_headers, "iso@x.com", rate_per_hour=2)
    async with proxy_client(key) as proxy:
        alice = [(await proxy.get("/cs/v1/whoami", headers={"X-Test-User": "alice"})).status_code
                 for _ in range(3)]
        bob = (await proxy.get("/cs/v1/whoami", headers={"X-Test-User": "bob"})).status_code
    assert alice == [200, 200, 429]   # alice exhausts her own bucket
    assert bob == 200                  # bob, a different end-user, is unaffected
