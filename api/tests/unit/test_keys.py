"""Phase 03 — key generation/hashing/parsing + origin matching (pure logic)."""
import pytest

from app.auth.keys import generate_key, hash_key, kind_from_key
from app.auth.origins import host_from_origin, origin_allowed


@pytest.mark.unit
def test_generate_client_key_shape():
    g = generate_key("client")
    assert g.raw.startswith("pk_live_")
    assert g.kind == "client" and g.prefix == "pk_live"
    assert g.last4 == g.raw[-4:]
    assert g.key_hash == hash_key(g.raw) and len(g.key_hash) == 64


@pytest.mark.unit
def test_generate_server_key_shape():
    g = generate_key("server")
    assert g.raw.startswith("sk_live_") and g.kind == "server"


@pytest.mark.unit
def test_keys_are_unique_and_high_entropy():
    raws = {generate_key("client").raw for _ in range(100)}
    assert len(raws) == 100


@pytest.mark.unit
def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        generate_key("bogus")


@pytest.mark.unit
@pytest.mark.parametrize("raw,expected", [
    ("pk_live_abc123", "client"),
    ("sk_live_abc123", "server"),
    ("pk_test_abc123", None),   # only _live_ keys are ours
    ("nope", None),
    ("pk_live", None),          # no secret segment
])
def test_kind_from_key(raw, expected):
    assert kind_from_key(raw) == expected


@pytest.mark.unit
@pytest.mark.parametrize("origin,expected", [
    ("https://app.example.com", "app.example.com"),
    ("https://app.example.com:8443", "app.example.com"),
    ("app.example.com", "app.example.com"),
    ("https://EXAMPLE.com/path?x=1", "example.com"),
    (None, None),
    ("", None),
])
def test_host_from_origin(origin, expected):
    assert host_from_origin(origin) == expected


@pytest.mark.unit
def test_origin_wildcard_allow_and_deny():
    allowed = ["https://*.example.com"]
    assert origin_allowed("app.example.com", allowed)
    assert origin_allowed("example.com", allowed)            # bare apex matches *.
    assert not origin_allowed("evil-example.com", allowed)   # not a subdomain
    assert not origin_allowed("example.com.evil.com", allowed)


@pytest.mark.unit
def test_origin_exact_match():
    allowed = ["https://site.com", "foo.bar"]
    assert origin_allowed("site.com", allowed)
    assert origin_allowed("foo.bar", allowed)
    assert not origin_allowed("other.com", allowed)


@pytest.mark.unit
def test_origin_denied_without_host():
    assert not origin_allowed(None, ["*.x.com"])
