"""bunny.net object storage adapter + the canonical key conventions.

bunny Storage is a plain HTTP API (NOT S3): writes go to
`https://{storage_host}/{zone}/{key}` with an `AccessKey` header; reads for hot objects
go through the zone's Pull Zone CDN host (`https://{cdn_host}/{key}`) so the serving API
never proxies payload bytes through itself. Everything bunny-specific lives here so the
rest of the code stays provider-agnostic (Stage 2.4).

`key` is the path *within* the zone (e.g. `42/canonical.zip`). The zone name (`demos`)
is the first path segment of the storage URL, and the pull zone is rooted at the zone, so
DB `storage_key` values and CDN URLs both use the within-zone key.
"""
from __future__ import annotations

import httpx

from ..config import settings

# Per-round payloads are content-addressed & versioned → cache forever, immutable.
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"


# --- key conventions (Stage 2.2) -------------------------------------------------------

def canonical_key(demo_id: int) -> str:
    """`Demo.compress()` parquet zip — the warm re-derivation cache."""
    return f"{demo_id}/canonical.zip"


def round_key(demo_id: int, payload_version: int, round_index: int) -> str:
    """Per-round viewer payload."""
    return f"{demo_id}/v{payload_version}/round-{round_index}.bin"


def index_key(demo_id: int, payload_version: int) -> str:
    """Round index (round list + map + scale ref + payload_version)."""
    return f"{demo_id}/v{payload_version}/index.json"


# --- adapter ---------------------------------------------------------------------------

class ObjectStore:
    """put/get/delete against a bunny Storage zone; `url()` builds the CDN read URL."""

    def __init__(
        self,
        *,
        storage_host: str,
        zone: str,
        storage_key: str,
        cdn_host: str,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.storage_host = storage_host.rstrip("/")
        self.zone = zone.strip("/")
        self.cdn_host = cdn_host.rstrip("/")
        self._access_key = storage_key
        self._timeout = timeout
        self._client = client            # injectable for tests; else created per call
        self._owns_client = client is None

    def _storage_url(self, key: str) -> str:
        return f"https://{self.storage_host}/{self.zone}/{key.lstrip('/')}"

    def url(self, key: str) -> str:
        """Public CDN (pull-zone) URL for a stored object."""
        if not self.cdn_host:
            raise RuntimeError("BUNNY_DEMOS_CDN_HOST is not configured")
        return f"https://{self.cdn_host}/{key.lstrip('/')}"

    async def _request(self, method: str, key: str, **kw) -> httpx.Response:
        headers = {"AccessKey": self._access_key, **kw.pop("headers", {})}
        if self._client is not None:
            return await self._client.request(method, self._storage_url(key), headers=headers, **kw)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            return await client.request(method, self._storage_url(key), headers=headers, **kw)

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        cache_control: str = IMMUTABLE_CACHE,
    ) -> str:
        """Upload bytes; returns the within-zone key. Raises on a non-2xx bunny response."""
        resp = await self._request(
            "PUT",
            key,
            content=data,
            headers={"Content-Type": content_type, "Cache-Control": cache_control},
        )
        resp.raise_for_status()
        return key

    async def get(self, key: str) -> bytes:
        """Download bytes via the Storage API (authenticated origin read)."""
        resp = await self._request("GET", key)
        resp.raise_for_status()
        return resp.content

    async def delete(self, key: str) -> None:
        """Delete an object (used by demo deletion in Stage 08/10)."""
        resp = await self._request("DELETE", key)
        if resp.status_code != 404:  # already-gone is fine for idempotent cleanup
            resp.raise_for_status()

    async def list_keys(self, prefix: str = "") -> list[str]:
        """Recursively list within-zone object keys under `prefix` (bunny Storage listing API).

        Used by the Stage 16 disaster-recovery rebuild to re-derive the demo→object mapping by
        scanning storage when the DB mapping is lost. bunny returns a JSON array per directory with
        `ObjectName` / `IsDirectory`; we walk directories depth-first. (Exercised at DR time against
        real bunny; tests use a fake store that implements this directly.)
        """
        out: list[str] = []

        async def walk(path: str) -> None:
            listing_key = path if path.endswith("/") or path == "" else path + "/"
            resp = await self._request("GET", listing_key)
            resp.raise_for_status()
            for obj in resp.json():
                name = obj.get("ObjectName")
                if not name:
                    continue
                full = f"{path.rstrip('/')}/{name}".lstrip("/") if path else name
                if obj.get("IsDirectory"):
                    await walk(full)
                else:
                    out.append(full)

        await walk(prefix.strip("/"))
        return out


def object_store(client: httpx.AsyncClient | None = None) -> ObjectStore:
    """Build the `demos`-zone ObjectStore (served, CDN-fronted: per-round payloads + index)."""
    return ObjectStore(
        storage_host=settings.bunny_demos_storage_host,
        zone=settings.bunny_demos_zone,
        storage_key=settings.bunny_demos_storage_key,
        cdn_host=settings.bunny_demos_cdn_host,
        client=client,
    )


def archive_store(client: httpx.AsyncClient | None = None) -> ObjectStore:
    """Build the COLD-archive ObjectStore (raw `.dem` source of truth, Stage 10).

    The archive zone has no public pull zone — it is never served to viewers, only read back
    for re-parse/backfill — so `cdn_host` is empty and `url()` is intentionally unavailable.
    """
    return ObjectStore(
        storage_host=settings.bunny_demos_storage_host,
        zone=settings.bunny_archive_zone or settings.bunny_demos_zone,
        storage_key=settings.bunny_archive_storage_key or settings.bunny_demos_storage_key,
        cdn_host="",
        client=client,
    )
