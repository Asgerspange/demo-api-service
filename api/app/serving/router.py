"""Stage 06 — serving API (`/v1`).

Read endpoints the embeddable viewer consumes, all aggressively cacheable and identical in
shape whether hit directly (client key) or via a customer proxy (server key):

- `GET /v1/demos/{id}`                 metadata + round index + map_ref + refs (short TTL)
- `GET /v1/demos/by-ref/{src}/{ext}`   same body, resolved by an integrator's own id
- `GET /v1/demos/{id}/rounds/{i}`      the per-round payload bytes (immutable + ETag, 304)
- `GET /v1/maps/{map}` / `GET /v1/maps`  calibration + radar URL from the seeded map_metadata
- `GET /v1/demos`                      the caller's demos, cursor-paginated + filterable

Authorization rides on the AuthContext (Stage 03): a key may only read demos its user owns;
an unowned/unknown demo or ref returns **404** (never 403) so ids aren't probeable across
tenants. Per-round payload bytes are read from object storage and streamed back gzipped — the
CDN-token-minting optimization (serving the bytes straight from the edge) is Stage 13; here we
serve through the API origin, which is safe and non-guessable.

Handlers take the injected `response` and set cache headers on it (returning a plain dict) so
the `X-RateLimit-*` headers added by `enforce_rate_limit` survive onto the final response —
the binary round endpoint copies those headers onto its raw `Response` for the same reason.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from ..auth.context import AuthContext
from ..auth.dependencies import require_server_key
from ..bandwidth import record_and_check
from ..config import settings
from ..db import get_pool
from ..lifecycle import delete_demo
from ..ratelimit import enforce_rate_limit
from ..redis import get_redis
from .cdn import demo_cdn_token
from ..storage.object_store import (
    IMMUTABLE_CACHE,
    ObjectStore,
    archive_store,
    object_store,
)
from ..storage.repos import CollectionRepo, DemoRepo, MapRepo, RefRepo, RoundRepo

router = APIRouter(prefix="/v1", tags=["serving"])

METADATA_CACHE = "public, max-age=60"      # metadata can change until ready → short TTL
MAPS_CACHE = "public, max-age=86400"       # calibration is reference data → long TTL


def get_store() -> ObjectStore:
    """Object store for reading payload bytes (overridden in tests)."""
    return object_store()


def get_archive_store() -> ObjectStore:
    """Cold-archive object store (raw .dem) — used by deletion (overridden in tests)."""
    return archive_store()


# --- shared builders -------------------------------------------------------------------

def _map_ref(map_row: dict | None) -> dict | None:
    """The calibration the viewer needs to map world X/Y → radar pixels (embedded in metadata)."""
    if map_row is None:
        return None
    return {
        "name": map_row["name"],
        "scale": map_row["scale"],
        "pos_x": map_row["pos_x"],
        "pos_y": map_row["pos_y"],
        "rotate": map_row["rotate"],
        "zoom": map_row["zoom"],
        "radar_url": map_row["image_path"],
        "levels": map_row.get("selections") or [],
    }


def _map_body(map_row: dict) -> dict:
    """Full `/v1/maps/{map}` body (calibration + radar URL) straight from map_metadata."""
    return {
        "name": map_row["name"],
        "display_name": map_row["display_name"],
        "pos_x": map_row["pos_x"],
        "pos_y": map_row["pos_y"],
        "scale": map_row["scale"],
        "rotate": map_row["rotate"],
        "zoom": map_row["zoom"],
        "selections": map_row.get("selections") or [],
        "radar_url": map_row["image_path"],
    }


async def _demo_body(pool, demo: dict, user_id: int) -> dict:
    """Assemble the `GET /v1/demos/{id}` body for a ready demo. Refs are filtered to the requesting
    tenant so a demo shared across tenants never exposes another tenant's ids."""
    rounds = await RoundRepo(pool).list_for_demo(demo["id"])
    refs = await RefRepo(pool).list_for_demo(demo["id"], user_id)
    map_row = await MapRepo(pool).get(demo["map"])
    meta = demo.get("meta") or {}
    return {
        "id": demo["id"],
        "map": demo["map"],
        "name": demo["name"],
        "status": demo["status"],
        "payload_version": demo["payload_version"],
        "round_count": demo["round_count"],
        "duration_ticks": demo["duration_ticks"],
        "refs": [{"source": r["source"], "external_id": r["external_id"]} for r in refs],
        "players": meta.get("steam", []),
        "scoreboard": meta.get("scoreboard", []),      # per-player match line (Stage 11 §11.2)
        "rounds": [{"round_index": r["round_index"], "meta": r["meta"]} for r in rounds],
        "map_ref": _map_ref(map_row),
        "map_supported": map_row is not None,                      # Stage 12 unknown-map state
        "calibration_suspect": bool(meta.get("calibration_suspect")),
        # Signed CDN token so the viewer fetches payloads from the edge (Stage 13); None in dev
        # (no token key) → the viewer falls back to the API round endpoint.
        "cdn": demo_cdn_token(demo["id"], demo["payload_version"]),
    }


async def _demo_payload(pool, demo: dict | None, response: Response, user_id: int) -> dict:
    """Ownership/readiness-checked demo metadata (shared by id + by-ref lookups).

    Caller passes None for unknown/unowned → 404. A not-yet-ready demo returns a pollable
    `409` with its status rather than a half-built body or a 500.
    """
    if demo is None:
        raise HTTPException(404, "demo not found")
    if demo["status"] != "ready":
        response.status_code = 409
        response.headers["Cache-Control"] = "no-store"
        return {"id": demo["id"], "status": demo["status"], "error": demo.get("error"),
                "detail": "demo is not ready yet; poll until status is 'ready'"}
    response.headers["Cache-Control"] = METADATA_CACHE
    return await _demo_body(pool, demo, user_id)


def _owned(demo: dict | None, ctx: AuthContext) -> dict | None:
    """Return the demo only if the caller is its CREATOR (else None → 404).

    Used for destructive ops (delete) which must stay restricted to the original owner even
    though a demo may be *readable* by several tenants. Read paths use DemoRepo.get_for_user()
    (access via demo_access) instead, so shared/deduped demos resolve for every granted tenant.
    """
    if demo is None or demo["owner_user_id"] != ctx.user_id:
        return None
    return demo


# --- demo metadata ---------------------------------------------------------------------

@router.get("/demos/{demo_id}")
async def get_demo(demo_id: int, response: Response,
                   ctx: AuthContext = Depends(enforce_rate_limit)) -> dict:
    pool = await get_pool()
    demo = await DemoRepo(pool).get_for_user(demo_id, ctx.user_id)
    return await _demo_payload(pool, demo, response, ctx.user_id)


@router.delete("/demos/{demo_id}")
async def delete_demo_endpoint(
    demo_id: int,
    ctx: AuthContext = Depends(require_server_key),     # destructive → server (secret) key only
    store: ObjectStore = Depends(get_store),
    archive: ObjectStore = Depends(get_archive_store),
) -> dict:
    """Delete the caller's demo: purges the demos zone (payloads + index + canonical) + the cold
    raw archive + DB rows (Stage 08/10). Requires a **server key** (not a public client key).
    Unowned/unknown → 404. Returns the removed keys."""
    pool = await get_pool()
    demo = _owned(await DemoRepo(pool).get(demo_id), ctx)
    if demo is None:
        raise HTTPException(404, "demo not found")
    result = await delete_demo(demo_id, pool=pool, store=store, archive=archive)
    return {"deleted": True, **(result or {})}


@router.get("/demos/by-ref/{source}/{external_id}")
async def get_demo_by_ref(source: str, external_id: str, response: Response,
                          ctx: AuthContext = Depends(enforce_rate_limit),
                          map: str | None = Query(default=None,
                              description="pick one map when a ref maps to several (Stage 18)")) -> dict:
    """Resolve a demo by an integrator's own id. A ref can map to several demos (one per map of a
    match, Stage 18) — `?map=` disambiguates; without it the first owned demo is returned. Use
    `/collections/by-ref` to get the whole match. Unknown/unowned → 404 (ids aren't probeable)."""
    pool = await get_pool()
    demos = DemoRepo(pool)
    demo = None
    for ref in await RefRepo(pool).resolve_all(source, external_id, ctx.user_id):
        owned = await demos.get_for_user(ref["demo_id"], ctx.user_id)
        if owned is None:
            continue
        if map and owned["map"] != map:
            continue
        demo = owned
        break
    return await _demo_payload(pool, demo, response, ctx.user_id)


async def _collection_body(pool, coll: dict) -> dict:
    """A collection (ingested archive/match) + its per-map demos (Stage 18 §18.3)."""
    demos = await DemoRepo(pool).list_for_collection(coll["id"])
    return {
        "id": coll["id"],
        "source": coll["source"],
        "external_id": coll["external_id"],
        "name": coll["name"],
        "demos": [{"id": d["id"], "map": d["map"], "name": d["name"], "status": d["status"],
                   "round_count": d["round_count"]} for d in demos],
    }


@router.get("/collections/by-ref/{source}/{external_id}")
async def get_collection_by_ref(source: str, external_id: str, response: Response,
                                ctx: AuthContext = Depends(enforce_rate_limit)) -> dict:
    """The collection for a match id + all its map demos — a host's map picker for an HLTV match.
    Cross-tenant/unknown → 404."""
    pool = await get_pool()
    coll = await CollectionRepo(pool).resolve(ctx.user_id, source, external_id)
    if coll is None:
        raise HTTPException(404, "collection not found")
    response.headers["Cache-Control"] = METADATA_CACHE
    return await _collection_body(pool, coll)


@router.get("/collections/{collection_id}")
async def get_collection(collection_id: int, response: Response,
                         ctx: AuthContext = Depends(enforce_rate_limit)) -> dict:
    pool = await get_pool()
    coll = await CollectionRepo(pool).get(collection_id)
    if coll is None or coll["owner_user_id"] != ctx.user_id:
        raise HTTPException(404, "collection not found")
    response.headers["Cache-Control"] = METADATA_CACHE
    return await _collection_body(pool, coll)


# --- per-round payload bytes -----------------------------------------------------------

@router.get("/demos/{demo_id}/rounds/{round_index}")
async def get_round(demo_id: int, round_index: int, request: Request, response: Response,
                    ctx: AuthContext = Depends(enforce_rate_limit),
                    store: ObjectStore = Depends(get_store)) -> Response:
    pool = await get_pool()
    demo = await DemoRepo(pool).get_for_user(demo_id, ctx.user_id)
    if demo is None:
        raise HTTPException(404, "demo not found")
    if demo["status"] != "ready":
        raise HTTPException(409, "demo is not ready yet")

    row = await RoundRepo(pool).get(demo_id, round_index)
    if row is None:
        raise HTTPException(404, "round not found")

    # The payload is immutable once ready, so a content-stable ETag lets us answer a
    # conditional request with 304 WITHOUT fetching the bytes from storage.
    etag = f'"d{demo_id}-v{demo["payload_version"]}-r{round_index}-{row["byte_size"]}"'
    headers = {"ETag": etag, "Cache-Control": IMMUTABLE_CACHE}
    # Carry the X-RateLimit-* headers enforce_rate_limit set on the injected response.
    headers.update({k: v for k, v in response.headers.items()
                    if k.lower().startswith("x-ratelimit")})

    if request.headers.get("If-None-Match") == etag:
        return Response(status_code=304, headers=headers)   # 304 serves no bytes → not counted

    # Per-tenant bandwidth cap (Stage 13 §13.3) — account the bytes, throttle once over.
    bw = await record_and_check(get_redis(), ctx, row["byte_size"])
    if bw["over"]:
        raise HTTPException(429, "bandwidth cap exceeded for this tenant",
                            headers={"Retry-After": str(settings.bandwidth_window_seconds)})

    blob = await store.get(row["storage_key"])
    # Bytes are gzipped JSON (v1); declare Content-Encoding so the browser transparently
    # inflates and the viewer worker's `response.json()` works (matches old getChunk).
    return Response(content=blob, media_type="application/json",
                    headers={**headers, "Content-Encoding": "gzip"})


# --- maps ------------------------------------------------------------------------------

@router.get("/maps")
async def list_maps(response: Response,
                    ctx: AuthContext = Depends(enforce_rate_limit)) -> dict:
    maps = await MapRepo(await get_pool()).list_all()
    response.headers["Cache-Control"] = MAPS_CACHE
    return {"items": [_map_body(m) for m in maps]}


@router.get("/maps/{map_name}")
async def get_map(map_name: str, response: Response,
                  ctx: AuthContext = Depends(enforce_rate_limit)) -> dict:
    row = await MapRepo(await get_pool()).get(map_name)
    if row is None:
        raise HTTPException(404, "unknown map")
    response.headers["Cache-Control"] = MAPS_CACHE
    return _map_body(row)


# --- listing ---------------------------------------------------------------------------

@router.get("/demos")
async def list_demos(
    response: Response,
    ctx: AuthContext = Depends(enforce_rate_limit),
    cursor: int | None = Query(default=None, description="return demos with id < cursor"),
    limit: int = Query(default=50, ge=1, le=100),
    map: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> dict:
    pool = await get_pool()
    demos = await DemoRepo(pool).list_for_user(
        ctx.user_id, limit=limit, before_id=cursor, map_name=map, status=status)
    refs_repo = RefRepo(pool)
    items = []
    for d in demos:
        refs = await refs_repo.list_for_demo(d["id"], ctx.user_id)
        items.append({
            "id": d["id"], "map": d["map"], "name": d["name"], "status": d["status"],
            "round_count": d["round_count"], "created_at": d["created_at"],
            "refs": [{"source": r["source"], "external_id": r["external_id"]} for r in refs],
        })
    # Full page → there may be more; hand back the last id as the next cursor.
    next_cursor = items[-1]["id"] if len(items) == limit else None
    response.headers["Cache-Control"] = "no-store"
    return {"items": items, "next_cursor": next_cursor}
