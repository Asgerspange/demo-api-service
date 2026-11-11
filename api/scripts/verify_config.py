"""Verify resolved config (from api/.env) and live-check each dependency.

    uv run python scripts/verify_config.py

Secrets are masked in output.
"""
import asyncio
import re

import httpx

from app.config import settings


def mask(v: str | None, show: int = 3) -> str:
    if not v:
        return "(empty)"
    if len(v) <= show * 2:
        return v[0] + "***"
    return f"{v[:show]}…{v[-show:]} (len {len(v)})"


def mask_url(u: str) -> str:
    return re.sub(r"(://[^:@/]*:)[^@]*(@)", r"\1***\2", u)


print("=== resolved config (from api/.env) ===")
print("app_env       :", settings.app_env)
print("db            :", f"{settings.db_user}@{settings.db_host}:{settings.db_port}/{settings.db_name}")
print("db_password   :", mask(settings.db_password))
print("redis_url     :", mask_url(settings.redis_url))
print("bunny storage :", settings.bunny_demos_storage_host, "| zone:", settings.bunny_demos_zone)
print("bunny key     :", mask(settings.bunny_demos_storage_key))
print("bunny cdn     :", settings.bunny_demos_cdn_host or "(empty)")
print("archive       :", "zone:", settings.bunny_archive_zone or "(empty)", "| key:", mask(settings.bunny_archive_storage_key))
print("steam key     :", mask(settings.steam_api_key))
print("admin token   :", mask(settings.admin_token))
print("api_version   :", settings.api_version, "| payload_version:", settings.payload_version)
print("max_demo_bytes:", settings.max_demo_bytes)
print("debug_demo    :", settings.debug_demo_path)


async def check_db() -> str:
    import aiomysql
    try:
        conn = await aiomysql.connect(
            host=settings.db_host, port=settings.db_port, user=settings.db_user,
            password=settings.db_password, db=settings.db_name, connect_timeout=5,
        )
        async with conn.cursor() as cur:
            await cur.execute("SELECT VERSION()")
            ver = (await cur.fetchone())[0]
            await cur.execute("SHOW TABLES")
            tables = [r[0] for r in await cur.fetchall()]
        conn.close()
        return f"OK — server {ver}, {len(tables)} tables {tables[:12]}"
    except Exception as e:  # noqa: BLE001
        return f"FAIL — {type(e).__name__}: {e}"


async def check_redis() -> str:
    from redis.asyncio import Redis
    try:
        r = Redis.from_url(settings.redis_url)
        await r.ping()
        info = await r.info("server")
        await r.aclose()
        return f"OK — redis {info.get('redis_version')}"
    except Exception as e:  # noqa: BLE001
        return f"FAIL — {type(e).__name__}: {e}"


async def check_bunny_storage() -> str:
    if not settings.bunny_demos_storage_key:
        return "skip (no key)"
    url = f"https://{settings.bunny_demos_storage_host}/{settings.bunny_demos_zone}/"
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.get(url, headers={"AccessKey": settings.bunny_demos_storage_key})
        if resp.status_code == 200:
            try:
                n = len(resp.json())
            except Exception:  # noqa: BLE001
                n = "?"
            return f"OK — 200, {n} object(s) at zone root"
        if resp.status_code == 401:
            return "FAIL — 401 Unauthorized (wrong AccessKey or zone name/host)"
        return f"unexpected HTTP {resp.status_code}: {resp.text[:120]}"
    except Exception as e:  # noqa: BLE001
        return f"FAIL — {type(e).__name__}: {e}"


async def check_cdn() -> str:
    host = settings.bunny_demos_cdn_host
    if not host:
        return "skip (no cdn host)"
    url = host if host.startswith("http") else f"https://{host}/"
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            resp = await c.get(url)
        return f"reachable — HTTP {resp.status_code}"
    except Exception as e:  # noqa: BLE001
        return f"FAIL — {type(e).__name__}: {e}"


async def main() -> None:
    print("\n=== live dependency checks ===")
    print("MySQL        :", await check_db())
    print("Redis        :", await check_redis())
    print("Bunny storage:", await check_bunny_storage())
    print("Bunny CDN    :", await check_cdn())


asyncio.run(main())
