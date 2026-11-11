"""Phase 02 — bunny.net ObjectStore adapter (bunny mocked with respx, no real network)."""
import httpx
import pytest
import respx

from app.storage.object_store import (
    IMMUTABLE_CACHE,
    ObjectStore,
    canonical_key,
    index_key,
    round_key,
)


def make_store(client: httpx.AsyncClient) -> ObjectStore:
    return ObjectStore(
        storage_host="storage.bunnycdn.com",
        zone="demos",
        storage_key="secret-access-key",
        cdn_host="demos.b-cdn.net",
        client=client,
    )


@pytest.mark.unit
def test_key_conventions():
    assert canonical_key(7) == "7/canonical.zip"
    assert round_key(7, 1, 0) == "7/v1/round-0.bin"
    assert index_key(7, 2) == "7/v2/index.json"


@pytest.mark.unit
def test_url_builds_cdn_pullzone_url():
    store = make_store(None)
    assert store.url("7/v1/round-0.bin") == "https://demos.b-cdn.net/7/v1/round-0.bin"


@pytest.mark.unit
def test_url_requires_cdn_host():
    store = ObjectStore(storage_host="storage.bunnycdn.com", zone="demos",
                        storage_key="k", cdn_host="")
    with pytest.raises(RuntimeError, match="CDN_HOST"):
        store.url("7/canonical.zip")


@pytest.mark.unit
async def test_put_uses_storage_api_with_access_key():
    async with httpx.AsyncClient() as client, respx.mock:
        route = respx.put("https://storage.bunnycdn.com/demos/7/canonical.zip").mock(
            return_value=httpx.Response(201)
        )
        key = await make_store(client).put(
            canonical_key(7), b"zip-bytes", content_type="application/zip"
        )
        assert key == "7/canonical.zip"
        req = route.calls.last.request
        assert req.headers["AccessKey"] == "secret-access-key"
        assert req.headers["Content-Type"] == "application/zip"
        assert req.headers["Cache-Control"] == IMMUTABLE_CACHE
        assert req.content == b"zip-bytes"


@pytest.mark.unit
async def test_get_roundtrips_bytes():
    async with httpx.AsyncClient() as client, respx.mock:
        respx.get("https://storage.bunnycdn.com/demos/7/v1/round-0.bin").mock(
            return_value=httpx.Response(200, content=b"payload")
        )
        data = await make_store(client).get(round_key(7, 1, 0))
        assert data == b"payload"


@pytest.mark.unit
async def test_put_raises_on_error_status():
    async with httpx.AsyncClient() as client, respx.mock:
        respx.put("https://storage.bunnycdn.com/demos/7/canonical.zip").mock(
            return_value=httpx.Response(401)
        )
        with pytest.raises(httpx.HTTPStatusError):
            await make_store(client).put(canonical_key(7), b"x")


@pytest.mark.unit
async def test_delete_tolerates_missing_object():
    async with httpx.AsyncClient() as client, respx.mock:
        respx.delete("https://storage.bunnycdn.com/demos/7/canonical.zip").mock(
            return_value=httpx.Response(404)
        )
        await make_store(client).delete(canonical_key(7))  # 404 must not raise
