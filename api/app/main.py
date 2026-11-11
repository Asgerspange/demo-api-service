"""FastAPI app factory.

Mounts /admin (owner-only) and the /v1 auth surface (Stage 03). Serving (/v1 demos/rounds/
maps) and /ingest routers land in later stages.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from .admin.router import router as admin_router
from .auth.router import router as auth_router
from .config import settings
from .db import close_pool
from .ingest.queue import close_arq
from .ingest.router import router as ingest_router
from .metrics import render_metrics, request_metrics_middleware
from .redis import close_redis
from .serving.router import router as serving_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Release shared clients on shutdown.
    await close_pool()
    await close_redis()
    await close_arq()


def create_app() -> FastAPI:
    app = FastAPI(title="Demoviewer API", default_response_class=ORJSONResponse,
                  lifespan=lifespan)

    # The embeddable viewer (Stage 07) runs on arbitrary customer origins and reads /v1 with a
    # Bearer client key (no cookies), so a wildcard CORS is safe: the real gate is the client
    # key's origin allowlist enforced in authenticate() (a wrong origin still gets 403). We
    # expose ETag so the viewer can do conditional round requests. allow_credentials stays
    # False — we never use cookies, and "*" + credentials is disallowed by the spec anyway.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["ETag", "X-RateLimit-Limit", "X-RateLimit-Remaining",
                        "X-RateLimit-Reset", "Retry-After"],
    )

    app.middleware("http")(request_metrics_middleware)

    app.include_router(admin_router)
    app.include_router(auth_router)
    app.include_router(ingest_router)
    app.include_router(serving_router)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        """Prometheus exposition — request/latency/429 counters + ingest queue/parse/status."""
        from .db import get_pool
        from .redis import get_redis

        body, content_type = await render_metrics(await get_pool(), get_redis())
        return Response(content=body, media_type=content_type)

    @app.get("/healthz")
    async def healthz() -> dict:
        """Liveness — process is up."""
        return {"status": "ok", "api_version": settings.api_version}

    @app.get("/readyz")
    async def readyz() -> ORJSONResponse:
        """Readiness — dependencies reachable."""
        checks: dict[str, str] = {}

        try:
            import aiomysql

            conn = await aiomysql.connect(
                host=settings.db_host,
                port=settings.db_port,
                user=settings.db_user,
                password=settings.db_password,
                db=settings.db_name,
                connect_timeout=3,
            )
            await conn.ping()
            conn.close()
            checks["db"] = "ok"
        except Exception as exc:  # noqa: BLE001 — surface the reason in the body
            checks["db"] = f"error: {exc}"

        try:
            from redis.asyncio import Redis

            r = Redis.from_url(settings.redis_url)
            await r.ping()
            await r.aclose()
            checks["redis"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["redis"] = f"error: {exc}"

        ready = all(v == "ok" for v in checks.values())
        return ORJSONResponse(
            {"ready": ready, "checks": checks},
            status_code=200 if ready else 503,
        )

    return app


app = create_app()
