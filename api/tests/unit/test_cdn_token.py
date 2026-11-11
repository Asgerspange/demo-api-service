"""Stage 13 §13.1 — bunny CDN token signing (determinism + URL-safety + scoping)."""
import pytest

from app.serving.cdn import demo_cdn_token, sign_directory

pytestmark = pytest.mark.unit


def test_sign_is_deterministic_and_url_safe():
    a = sign_directory("/42/v1/", 1_000, "secret")
    b = sign_directory("/42/v1/", 1_000, "secret")
    assert a == b
    assert "+" not in a and "/" not in a and "=" not in a   # URL-safe base64

    # any input change → different token
    assert sign_directory("/42/v1/", 1_001, "secret") != a   # expiry
    assert sign_directory("/43/v1/", 1_000, "secret") != a   # demo (scope)
    assert sign_directory("/42/v1/", 1_000, "other") != a    # key


def test_demo_cdn_token_block():
    tok = demo_cdn_token(42, 1, cdn_host="demos.b-cdn.net", security_key="k", ttl=3600, now=1000)
    assert tok["base"] == "https://demos.b-cdn.net"
    assert tok["expires"] == 4600
    assert tok["token_path"] == "/42/v1/"
    assert tok["token"] == sign_directory("/42/v1/", 4600, "k")


def test_no_token_when_unconfigured():
    # missing CDN host or token key → no token block (viewer falls back to the API)
    assert demo_cdn_token(42, 1, cdn_host="", security_key="k") is None
    assert demo_cdn_token(42, 1, cdn_host="demos.b-cdn.net", security_key="") is None
