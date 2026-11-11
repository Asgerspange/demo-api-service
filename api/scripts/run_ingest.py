"""Run the Stage 05 ingestion pipeline live against a local .dem (debug/manual).

Drives the real worker pipeline (real awpy parse + real round-payload build), printing a
timed line per stage so you can see where the time goes.

    uv run python scripts/run_ingest.py ../demo.dem            # local-disk object store
    uv run python scripts/run_ingest.py ../demo.dem --bunny    # real bunny zones (needs config)

Without --bunny, artifacts land under ./_ingest_out/{demos,archive} (no cloud config needed).
With --bunny, they go to the configured bunny `demos` + archive zones. The demo + round rows
go to the configured DB (defaults to the dev Percona on :3307) either way.
"""
import asyncio
import os
import sys
import time
from pathlib import Path

# Allow `import app...` when run from api/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.db import create_pool  # noqa: E402
from app.ingest.pipeline import run_pipeline  # noqa: E402
from app.storage.migrate import apply_migrations  # noqa: E402
from app.storage.object_store import archive_store, object_store  # noqa: E402
from app.storage.repos import DemoRepo, JobRepo, RoundRepo, UserRepo  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "_ingest_out"


class LocalStore:
    """ObjectStore-compatible store that writes objects under a local directory."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.count = 0
        self.bytes = 0

    async def put(self, key, data, *, content_type="application/octet-stream",
                  cache_control="") -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes(data))
        self.count += 1
        self.bytes += len(data)
        return key


async def main(dem_path: str, use_bunny: bool) -> int:
    settings.max_demo_bytes = max(settings.max_demo_bytes, os.path.getsize(dem_path) + 1)

    pool = await create_pool()
    try:
        applied = await apply_migrations(pool)
        if applied:
            print(f"applied migrations: {applied}")

        users = UserRepo(pool)
        user = await users.get_by_email("local-ingest@dev")
        uid = user["id"] if user else await users.create("local-ingest@dev", "Local Ingest")

        job_id = f"local-{int(time.time())}"
        jobs = JobRepo(pool)
        await jobs.create(job_id, "path", str(dem_path), user_id=uid, status="queued")
        await jobs.update(job_id, progress={"request": {
            "name": Path(dem_path).name,
            "refs": [{"source": "local", "external_id": job_id}],
        }})

        if use_bunny:
            store, archive = object_store(), archive_store()
            dest = f"bunny zone={settings.bunny_demos_zone} / archive={settings.bunny_archive_zone or '(demos)'}"
        else:
            store = LocalStore(OUT / "demos")
            archive = LocalStore(OUT / "archive")
            dest = str(OUT)

        print(f"\n▶ ingesting {dem_path} (job {job_id}) → {dest}\n")
        t0 = time.perf_counter()

        def on_event(msg: str) -> None:
            print(f"  · {time.perf_counter() - t0:6.1f}s  {msg}", flush=True)

        await run_pipeline(pool=pool, job_id=job_id, store=store, archive=archive,
                           on_event=on_event)
        dt = time.perf_counter() - t0

        job = await jobs.get(job_id)
        print(f"\n── job {job_id}: status={job['status']} in {dt:.1f}s")
        if job["status"] != "ready":
            print(f"   error: {job['error']}")
            print(f"   progress: {job['progress']}")
            return 1

        demo_id = job["demo_id"]
        demo = await DemoRepo(pool).get(demo_id)
        rounds = await RoundRepo(pool).list_for_demo(demo_id)
        print(f"── demo {demo_id}: map={demo['map']} rounds={demo['round_count']} "
              f"duration_ticks={demo['duration_ticks']}")
        print(f"   sha256={demo['sha256']}")
        print(f"   canonical={demo['storage_key']}  raw={demo['raw_storage_key']} "
              f"({demo['raw_codec']}, {demo['raw_bytes']:,} bytes)")
        if isinstance(store, LocalStore):
            print(f"   warm/hot objects: {store.count} files, {store.bytes:,} bytes")
            print(f"   cold archive:     {archive.count} files, {archive.bytes:,} bytes")
            print(f"   artifacts written under: {OUT}")
        else:
            print(f"   uploaded to bunny: demos zone + archive zone")
        print(f"   demo_rounds rows: {len(rounds)}")
        sample = rounds[0]
        print(f"   sample round {sample['round_index']}: {sample['byte_size']:,} bytes "
              f"-> {sample['storage_key']}  meta={sample['meta']}")
        return 0
    finally:
        pool.close()
        await pool.wait_closed()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    use_bunny = "--bunny" in sys.argv[1:]
    if not args:
        print("usage: run_ingest.py <path-to-.dem> [--bunny]")
        raise SystemExit(2)
    raise SystemExit(asyncio.run(main(args[0], use_bunny)))
