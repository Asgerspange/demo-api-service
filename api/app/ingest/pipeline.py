"""The arq ingestion job (Stage 5.2): acquire → extract → dedup → classify → archive →
parse → canonical zip → per-round payloads → finalize.

Each step updates `ingest_jobs.progress`; failures set the job (and any demo row) to `failed`
with a reason and are *not* re-raised, so arq doesn't auto-retry a deterministically-bad demo
(a transient infra failure surfaces as a `failed` job the caller can re-submit). The network
download and the parse both run under hard timeouts, and the temp `.dem` is always removed.

`run_pipeline` takes injectable `acquire`/`parse`/`classify` hooks so the orchestration can be
tested without real network or a real awpy parse; the production defaults do the real work.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import tempfile
import time
from typing import Awaitable, Callable

import httpx
import orjson
from loguru import logger

from ..config import settings
from ..payload import build_index, encode_round, validate_round
from ..storage.object_store import (
    ObjectStore,
    canonical_key,
    index_key,
    round_key,
)
from ..storage.repos import CollectionRepo, DemoRepo, JobRepo, MapRepo, RefRepo, RoundRepo
from .acquire import download, read_path
from .archive import compress_raw, raw_archive_key
from .calibration import check_calibration, sample_positions
from .canonical import frames_to_zip
from .classify import Classification, classify_demo
from .errors import DownloadError, IngestError
from .extract import extract_dems
from .rounds import build_parse_report, build_round_records, build_scoreboard, frames_from_demo

# The player properties the parser must extract for the payload + meta (ported verbatim from
# demo_processor.py so the dataframes carry every field create_tick_dict / the stats need).
PLAYER_PROPS = [
    "balance", "active_weapon_name", "is_in_reload", "is_walking", "pitch",
    "armor_value", "flash_duration", "has_defuser", "has_helmet",
    "inventory", "team_clan_name", "yaw", "kills_total", "deaths_total",
    "assists_total", "enemies_flashed_total", "equipment_value_total",
    "utility_damage_total", "ace_rounds_total", "4k_rounds_total",
    "3k_rounds_total", "damage_total", "crosshair_code", "leader_honors",
    "teacher_honors", "friendly_honors", "headshot_kills_total", "ping",
    "mvps", "rank", "rank_if_win", "rank_if_loss", "rank_if_tie", "comp_rank_type",
]

AcquireFn = Callable[[dict], Awaitable[bytes]]
ParseFn = Callable[[str], object]
ClassifyFn = Callable[[str], Classification]
WebhookFn = Callable[[str, dict], Awaitable[None]]


# --- production default hooks -----------------------------------------------------------

async def _default_acquire(job: dict) -> bytes:
    """Fetch the raw container bytes for a job's source (url download / local path read)."""
    st, ref = job["source_type"], job["source_ref"]
    if st == "url":
        return await download(ref, max_bytes=settings.max_demo_bytes,
                              timeout=settings.ingest_download_timeout)
    if st == "path":
        return read_path(ref, max_bytes=settings.max_demo_bytes)
    raise DownloadError(f"unknown source_type: {st!r}")


def _default_parse(dem_path: str):
    """Full awpy parse with the player props the payload needs."""
    from awpy import Demo

    dem = Demo(path=dem_path, verbose=False)
    dem.parse(player_props=PLAYER_PROPS)
    return dem


async def _steam_summaries(ticks_df) -> list:
    """Optional Steam player summaries (TLS verification is ON — the old TLS-disabled call is fixed)."""
    steamids = [s for s in ticks_df["steamid"].dropna().unique().tolist() if s]
    if not steamids:
        return []
    url = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/"
    params = {"key": settings.steam_api_key, "steamids": ",".join(map(str, steamids))}
    try:
        async with httpx.AsyncClient(timeout=10) as client:  # verify=True by default
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json().get("response", {}).get("players", [])
    except Exception as exc:  # noqa: BLE001 — summaries are best-effort, never fatal
        logger.warning(f"steam summaries failed: {exc}")
        return []


async def _default_webhook(url: str, payload: dict) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(url, json=payload)


# --- ref attachment + webhook -----------------------------------------------------------

async def _attach_refs(refs: RefRepo, demo_id: int, job_refs: list, user_id: int) -> None:
    """Attach external refs to a demo, scoped to the ingesting tenant (a ref MAY be shared across an
    archive's maps — one HLTV match id → every map). Idempotent per (demo, source, external_id, user)."""
    for r in job_refs or []:
        source, ext = r.get("source"), r.get("external_id")
        if not source or ext in (None, ""):
            continue
        await refs.add(demo_id, source, str(ext), user_id)


async def _ensure_webhook_secret(pool, user_id: int | None) -> str:
    """Return the tenant's webhook signing secret, generating + persisting one on first use."""
    from ..storage.repos import UserRepo
    from ..webhooks import new_secret

    if user_id is None:
        return ""
    users = UserRepo(pool)
    row = await users.get(user_id)
    secret = (row or {}).get("webhook_secret")
    if not secret:
        secret = new_secret()
        await users.set_webhook_secret(user_id, secret)
    return secret


async def _fire_webhook(*, pool, url: str | None, user_id: int | None, job_id: str,
                        demo_id: int | None, status: str, post: WebhookFn | None) -> None:
    """Fire the completion webhook (Stage 16 §16.2).

    Default path: enqueue a **durable, HMAC-signed** delivery (retry-with-backoff → dead-letter) so a
    slow/failing customer endpoint never delays ingest. Tests inject `post` for an inline delivery.
    """
    if not url:
        return
    payload = {"event": f"demo.{status}", "job_id": job_id, "demo_id": demo_id, "status": status}
    try:
        if post is not None:                      # inline override (tests)
            await post(url, payload)
            return
        secret = await _ensure_webhook_secret(pool, user_id)
        from .queue import enqueue_webhook
        await enqueue_webhook({"url": url, "payload": payload, "secret": secret,
                               "user_id": user_id, "job_id": job_id})
    except Exception as exc:  # noqa: BLE001 — a webhook failure must not fail the ingest
        logger.warning(f"webhook enqueue to {url} failed: {exc}")


# --- orchestration ----------------------------------------------------------------------

async def run_pipeline(
    *,
    pool,
    job_id: str,
    store: ObjectStore,
    archive: ObjectStore,
    acquire: AcquireFn | None = None,
    parse: ParseFn | None = None,
    classify: ClassifyFn | None = None,
    webhook_post: WebhookFn | None = None,
    on_event: Callable[[str], None] | None = None,
) -> None:
    jobs, demos = JobRepo(pool), DemoRepo(pool)
    rounds, refs = RoundRepo(pool), RefRepo(pool)

    job = await jobs.get(job_id)
    if job is None:
        raise RuntimeError(f"ingest job {job_id} not found")

    request = (job.get("progress") or {}).get("request") or {}
    name = request.get("name") or f"demo-{job_id[:8]}"
    job_refs = request.get("refs") or []
    anonymize = bool(request.get("anonymize"))
    force = bool(request.get("force"))   # re-parse in place even on a ready dedup hit
    owner = job["user_id"]
    webhook_url = job.get("webhook_url")
    demo_id = job.get("demo_id")
    warnings: list[str] = []

    acquire = acquire or _default_acquire
    parse = parse or _default_parse
    classify = classify or classify_demo
    pv = settings.payload_version

    async def progress(stage: str, *, status: str | None = None,
                       did: int | None = None, **extra) -> None:
        prog = {"request": request, "stage": stage, **extra}
        if warnings:
            prog["warnings"] = warnings
        await jobs.update(job_id, status=status, demo_id=did, progress=prog)

    def emit(msg: str) -> None:
        """Log a human-readable stage line (with timing) for live progress."""
        logger.info(f"[ingest {job_id[:8]}] {msg}")
        if on_event:
            on_event(msg)

    # ── per-demo processing (shared by the single-demo and multi-demo-archive paths, Stage 18) ──
    async def process_one(dem_bytes: bytes, dem_name: str, dem_path: str,
                          collection_id: int | None) -> int:
        """Dedup → classify → parse → canonical → payloads → ready → archive ONE demo.

        Returns the demo id (a new ready demo, or an already-ready dedup hit). Raises on a hard
        failure; the caller decides whether that fails the whole job or just this demo of an archive.
        `demo_id` is set as soon as the row exists so a failure can mark exactly that demo.
        """
        nonlocal demo_id
        from ..metrics import INGEST_OUTCOMES, PARSE_SECONDS

        sha = hashlib.sha256(dem_bytes).hexdigest()

        # Dedup: an already-ready demo with this hash short-circuits the parse (idempotency) — we
        # only attach any new refs + (re)link the collection (the cheap HLTV re-submit path).
        # `force` skips the short-circuit so the demo is re-parsed in place (the reuse branch
        # below updates the existing row), e.g. to backfill stats added after the first parse.
        existing = await demos.get_by_sha256(sha)
        if existing and existing["status"] == "ready" and not force:
            await _attach_refs(refs, existing["id"], job_refs, owner)
            # Grant THIS tenant access to the deduped demo — without it the row stays visible
            # only to whoever first ingested the content (serving 404s for everyone else).
            await demos.grant_access(existing["id"], owner)
            # And add it to THIS tenant's collection (membership is many-to-many).
            if collection_id is not None:
                await demos.add_to_collection(existing["id"], collection_id)
            await progress("dedup", status="parsing", did=existing["id"], deduped=True)
            INGEST_OUTCOMES.labels("deduped").inc()
            return existing["id"], True

        with open(dem_path, "wb") as fp:
            fp.write(dem_bytes)

        # Classify (cheap header probe) before paying for a full parse — rejects CSGO etc.
        t = time.perf_counter()
        cls = await asyncio.to_thread(classify, dem_path)
        emit(f"classified {dem_name}: map={cls.map_name} gotv={cls.is_gotv} "
             f"in {time.perf_counter() - t:.1f}s")

        if existing:                       # reuse a prior failed/partial row for this hash
            did = existing["id"]
            await demos.update_status(did, "parsing")
            if collection_id is not None:
                await demos.add_to_collection(did, collection_id)
        else:
            did = await demos.create(
                owner, sha, cls.map_name, dem_name, status="parsing",
                payload_version=pv, retention_tier="standard", collection_id=collection_id,
            )
        demo_id = did                      # expose for failure marking (nonlocal)
        await demos.grant_access(did, owner)   # the creating tenant can always read its own demo
        await progress("parse", status="parsing", did=did)
        t = time.perf_counter()
        dem = await asyncio.wait_for(
            asyncio.to_thread(parse, dem_path), settings.ingest_parse_timeout)
        PARSE_SECONDS.observe(time.perf_counter() - t)
        emit(f"parsed {dem_name} in {time.perf_counter() - t:.1f}s")

        frames = await asyncio.to_thread(frames_from_demo, dem)
        if anonymize:
            from .privacy import anonymize_frames
            frames = await asyncio.to_thread(anonymize_frames, frames)
            emit("anonymized steamids/names (per-demo aliases)")

        records = await asyncio.to_thread(build_round_records, frames)
        emit(f"built {len(records)} round records for {dem_name}")

        # Canonical parquet zip (warm re-derivation cache) → the cold archive zone (Stage 10/14).
        await progress("canonical", did=did)
        canonical = await asyncio.to_thread(frames_to_zip, frames)
        await archive.put(canonical_key(did), canonical, content_type="application/zip")

        # Per-round payloads → hot tier, bounded-concurrency upload.
        await progress("payloads", did=did)
        sem = asyncio.Semaphore(settings.ingest_round_upload_concurrency)

        async def upload(rec) -> dict:
            validate_round(rec.record)
            blob = encode_round(rec.record, level=settings.payload_gzip_level)
            key = round_key(did, pv, rec.round_index)
            async with sem:
                await store.put(key, blob)
            await rounds.upsert(did, rec.round_index, key, len(blob), rec.light_meta)
            return {"round_index": rec.round_index, "storage_key": key,
                    "byte_size": len(blob), "meta": rec.light_meta}

        index_rounds = await asyncio.gather(*[upload(r) for r in records])
        index_rounds.sort(key=lambda r: r["round_index"])
        index = build_index(did, cls.map_name, index_rounds,
                            payload_version=pv, api_version=settings.api_version)
        await store.put(index_key(did, pv), orjson.dumps(index),
                        content_type="application/json")

        # Map calibration + drift check (Stage 12).
        map_row = await MapRepo(pool).get(cls.map_name)
        calibration = check_calibration(map_row, sample_positions(frames.ticks))
        calibration["map_supported"] = map_row is not None
        if map_row is None:
            emit(f"⚠ unknown map '{cls.map_name}' — no calibration (viewer shows unsupported state)")
        elif calibration["suspect"]:
            emit(f"⚠ calibration_suspect for {cls.map_name}: "
                 f"{calibration['in_bounds_fraction']} of positions on the radar")

        report = build_parse_report(cls, frames, records)
        report["calibration"] = calibration
        scoreboard = build_scoreboard(frames, len(records))
        meta = {
            "scoreboard": scoreboard,
            "header": cls.header,
            "classification": {"is_gotv": cls.is_gotv, "demo_version": cls.demo_version},
            "calibration_suspect": bool(calibration["suspect"]),
            "map_supported": map_row is not None,
            "anonymized": anonymize,
            "parse_report": report,
        }
        if not anonymize and settings.ingest_steam_summaries and settings.steam_api_key:
            meta["steam"] = await _steam_summaries(frames.ticks)

        duration_ticks = int(frames.ticks["tick"].max()) if not frames.ticks.empty else 0
        await demos.set_ready(did, round_count=len(records), duration_ticks=duration_ticks,
                              storage_key=canonical_key(did), meta=meta)
        # Attach the request refs (shared across an archive's maps) + a per-map ref so a shared match
        # id is disambiguable by map via by-ref?map (Stage 18 §18.3).
        await _attach_refs(refs, did, job_refs, owner)
        INGEST_OUTCOMES.labels("ready").inc()
        emit(f"READY demo_id={did} map={cls.map_name} rounds={len(records)}")

        # Cold-archive the raw .dem LAST (post-ready housekeeping; never gates serving).
        try:
            comp = await asyncio.to_thread(compress_raw, dem_bytes)
            akey = raw_archive_key(did)
            await archive.put(akey, comp, content_type="application/zstd")
            await demos.set_raw_archive(did, raw_storage_key=akey, raw_codec="zstd",
                                        raw_bytes=len(comp))
        except Exception as exc:  # noqa: BLE001 — archive is post-ready housekeeping
            logger.warning(f"raw archive for demo {did} failed (demo stays ready): {exc}")
            warnings.append(f"raw archive failed for demo {did}: {exc}")
        return did, False

    tmpdir: str | None = None
    try:
        await progress("acquire", status="downloading")
        t = time.perf_counter()
        container = await acquire(job)
        dems = extract_dems(container, max_bytes=settings.max_demo_bytes,
                            max_members=settings.ingest_zip_max_members)
        emit(f"acquired + extracted {len(dems)} demo(s) in {time.perf_counter() - t:.1f}s")
        tmpdir = tempfile.mkdtemp(prefix="ingest-")

        if len(dems) == 1:
            # ── single demo: the proven Stage 05 path ──
            demo_id, deduped = await process_one(
                dems[0].data, name, os.path.join(tmpdir, "demo.dem"), None)
            await progress("ready", status="ready", did=demo_id,
                           **({"deduped": True} if deduped else {}))
            await _fire_webhook(pool=pool, url=webhook_url, user_id=owner, job_id=job_id,
                                demo_id=demo_id, status="ready", post=webhook_post)
            return

        # ── multi-demo archive (HLTV match): one collection, one demo per map (Stage 18) ──
        # The archive's shared identity (e.g. an HLTV match id) comes from the first request ref.
        first_ref = (job_refs or [{}])[0]
        cid = await CollectionRepo(pool).get_or_create(
            owner, source=first_ref.get("source"),
            external_id=(str(first_ref["external_id"]) if first_ref.get("external_id") else None),
            name=name)
        emit(f"multi-demo archive → collection {cid} ({len(dems)} demos)")

        demo_ids: list[int] = []
        for i, ex in enumerate(dems):
            demo_id = None              # reset so a per-demo failure marks the right row (or none)
            try:
                did, _ = await process_one(ex.data, ex.name,
                                           os.path.join(tmpdir, f"demo-{i}.dem"), cid)
                demo_ids.append(did)
            except Exception as exc:  # noqa: BLE001 — one bad map shouldn't sink the rest
                msg = exc.message if isinstance(exc, IngestError) else f"{type(exc).__name__}: {exc}"
                logger.error(f"ingest job {job_id}: demo {ex.name} failed: {msg}")
                warnings.append(f"{ex.name}: {msg}")
                if demo_id:             # mark the partially-created demo failed, not dangling
                    await demos.update_status(demo_id, "failed", msg)

        if not demo_ids:
            raise IngestError("no demo in the archive could be ingested")

        # Job points at the first demo; the collection + all demo ids are in progress.
        await progress("ready", status="ready", did=demo_ids[0],
                       collection_id=cid, demo_ids=demo_ids)
        from ..metrics import INGEST_OUTCOMES
        INGEST_OUTCOMES.labels("ready").inc()
        emit(f"READY collection {cid}: {len(demo_ids)}/{len(dems)} demos")
        await _fire_webhook(pool=pool, url=webhook_url, user_id=owner, job_id=job_id,
                            demo_id=demo_ids[0], status="ready", post=webhook_post)

    except Exception as exc:  # noqa: BLE001 — record the failure, never crash the worker loop
        msg = exc.message if isinstance(exc, IngestError) else f"{type(exc).__name__}: {exc}"
        logger.error(f"ingest job {job_id} failed: {msg}")
        from ..metrics import INGEST_OUTCOMES
        INGEST_OUTCOMES.labels("failed").inc()
        await jobs.update(job_id, status="failed", demo_id=demo_id, error=msg)
        if demo_id:
            await demos.update_status(demo_id, "failed", msg)
        await _fire_webhook(pool=pool, url=webhook_url, user_id=owner, job_id=job_id,
                            demo_id=demo_id, status="failed", post=webhook_post)
    finally:
        if tmpdir and os.path.isdir(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)


async def ingest_demo(ctx: dict, job_id: str) -> None:
    """arq task entrypoint — wired in app/worker.py.

    Per-tenant fairness (Stage 16 §16.1): before parsing, take one of the tenant's bounded
    concurrent-parse slots. If they're at their cap, re-enqueue this job with a short defer and
    free the worker immediately — so one tenant's 500-demo batch occupies at most `cap` workers and
    can never stall another tenant's single demo. The slot is released in `finally`.
    """
    from ..fairness import acquire_slot, release_slot
    from ..storage.repos import JobRepo

    pool = ctx["pool"]
    redis = ctx.get("redis")               # arq injects the pool; absent in some unit harnesses
    cap = settings.ingest_tenant_max_inflight
    user_id = None

    if redis is not None and cap > 0:
        job = await JobRepo(pool).get(job_id)
        user_id = job and job.get("user_id")
        if user_id is not None and not await acquire_slot(redis, user_id, cap):
            lane = ctx.get("queue_name") or "arq:queue:live:standard"
            await redis.enqueue_job("ingest_demo", job_id, _queue_name=lane,
                                    _defer_by=settings.ingest_defer_seconds)
            return

    try:
        await run_pipeline(
            pool=pool, job_id=job_id, store=ctx["store"], archive=ctx["archive"]
        )
    finally:
        if user_id is not None and redis is not None and cap > 0:
            await release_slot(redis, user_id)
