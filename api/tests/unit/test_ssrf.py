"""Stage 05 — SSRF host classification + download guard (security-required)."""
import httpx
import pytest

from app.ingest.acquire import download
from app.ingest.errors import DownloadError, SSRFError, TooLargeError
from app.ingest.security import assert_url_allowed, ip_is_blocked

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1", "169.254.169.254",
    "100.64.0.1", "0.0.0.0", "::1", "fd00::1", "::ffff:10.0.0.1",
])
def test_blocked_ranges(ip):
    assert ip_is_blocked(ip) is True


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700::1111"])
def test_public_ranges_allowed(ip):
    assert ip_is_blocked(ip) is False


def test_assert_url_rejects_private_literal():
    with pytest.raises(SSRFError):
        assert_url_allowed("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(SSRFError):
        assert_url_allowed("http://127.0.0.1:8000/x.dem")


def test_assert_url_rejects_non_http_scheme():
    with pytest.raises(SSRFError):
        assert_url_allowed("file:///etc/passwd")
    with pytest.raises(SSRFError):
        assert_url_allowed("gopher://evil/x")


def test_assert_url_allows_public_literal():
    assert assert_url_allowed("https://8.8.8.8/demo.dem") == ["8.8.8.8"]


async def test_download_refuses_redirect():
    """A 30x must not be followed — it could bounce onto an internal host post-DNS-check."""
    def handler(request):
        return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, follow_redirects=False)
    with pytest.raises(DownloadError, match="redirect"):
        await download("https://8.8.8.8/demo.dem", max_bytes=1_000, timeout=5, client=client)


async def test_download_enforces_size_cap_streaming():
    def handler(request):
        return httpx.Response(200, content=b"x" * 5_000)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    with pytest.raises(TooLargeError):
        await download("https://8.8.8.8/big.dem", max_bytes=1_000, timeout=5, client=client)


async def test_download_rejects_oversize_content_length():
    def handler(request):
        return httpx.Response(200, headers={"content-length": "999999"}, content=b"x")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    with pytest.raises(TooLargeError):
        await download("https://8.8.8.8/big.dem", max_bytes=1_000, timeout=5, client=client)


async def test_download_pins_to_validated_ip(monkeypatch):
    """The connection must target the IP that was validated, not re-resolve the hostname —
    closing the DNS-rebinding TOCTOU (host pinned, original Host header preserved)."""
    import app.ingest.acquire as acq
    monkeypatch.setattr(acq, "assert_url_allowed", lambda u: ["93.184.216.34"])

    seen = {}

    def handler(request):
        seen["host"] = request.url.host
        seen["host_header"] = request.headers.get("host")
        return httpx.Response(200, content=b"PBDEMS2ok")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    out = await acq.download("https://demos.faceit.com/x.dem",
                             max_bytes=1000, timeout=5, client=client)
    assert out == b"PBDEMS2ok"
    assert seen["host"] == "93.184.216.34"                 # dialed the validated IP
    assert seen["host_header"].startswith("demos.faceit.com")  # original Host preserved (vhost/TLS)


async def test_download_blocks_private_before_connecting():
    """SSRF check fires before any transport use."""
    called = False

    def handler(request):
        nonlocal called
        called = True
        return httpx.Response(200, content=b"ok")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(SSRFError):
        await download("http://127.0.0.1/x.dem", max_bytes=1_000, timeout=5, client=client)
    assert called is False
