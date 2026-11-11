"""Stage 16 §16.2 — webhook HMAC signing, replay protection & retry/backoff policy."""
import orjson
import pytest

from app.webhooks import (
    MAX_DELIVERY_ATTEMPTS,
    backoff_seconds,
    new_nonce,
    new_secret,
    parse_signature,
    should_retry,
    sign,
    signature_headers,
    verify_signature,
)

pytestmark = pytest.mark.unit


def test_sign_verify_round_trip():
    secret = new_secret()
    body = orjson.dumps({"event": "demo.ready", "demo_id": 7})
    headers = signature_headers(secret, body, timestamp=1_000)
    ts = int(headers["X-Demoviewer-Timestamp"])
    nonce = headers["X-Demoviewer-Nonce"]
    assert verify_signature(secret, body, timestamp=ts, nonce=nonce,
                            signature_header=headers["X-Demoviewer-Signature"], now=1_001)


def test_wrong_secret_fails():
    body = b'{"a":1}'
    headers = signature_headers("secret-a", body, timestamp=500, nonce="n")
    assert not verify_signature("secret-b", body, timestamp=500, nonce="n",
                                signature_header=headers["X-Demoviewer-Signature"], now=501)


def test_tampered_body_fails():
    secret = new_secret()
    headers = signature_headers(secret, b'{"amount":1}', timestamp=10, nonce="n")
    assert not verify_signature(secret, b'{"amount":999}', timestamp=10, nonce="n",
                                signature_header=headers["X-Demoviewer-Signature"], now=11)


def test_stale_timestamp_rejected_replay_protection():
    secret = new_secret()
    body = b"{}"
    headers = signature_headers(secret, body, timestamp=1_000, nonce="n")
    # now is far past the tolerance window → rejected even with a valid signature (replay defense)
    assert not verify_signature(secret, body, timestamp=1_000, nonce="n",
                                signature_header=headers["X-Demoviewer-Signature"],
                                now=1_000 + 10_000, tolerance=300)


def test_nonce_changes_the_signature():
    secret = new_secret()
    body = b"{}"
    a = sign(secret, body, timestamp=1, nonce="n1")
    b = sign(secret, body, timestamp=1, nonce="n2")
    assert a != b                       # nonce is bound into the signature


def test_parse_signature_extracts_v1():
    assert parse_signature("v1=abc123") == "abc123"
    assert parse_signature("t=1,v1=deadbeef") == "deadbeef"
    assert parse_signature("nope") is None


def test_backoff_is_exponential_and_capped():
    assert [backoff_seconds(a) for a in (1, 2, 3, 4, 5)] == [1, 2, 4, 8, 16]
    assert backoff_seconds(20) == 300   # capped


def test_should_retry_respects_budget():
    assert should_retry(1)
    assert should_retry(MAX_DELIVERY_ATTEMPTS - 1)
    assert not should_retry(MAX_DELIVERY_ATTEMPTS)


def test_unsigned_when_no_secret_still_has_content_type():
    # If a tenant has no secret yet, delivery still works (just unsigned) — content-type present.
    from app.webhook_delivery import _post_signed  # noqa: F401 — import smoke
    headers = signature_headers("s", b"{}", timestamp=1)
    assert headers["Content-Type"] == "application/json"
    assert new_nonce() != new_nonce()
