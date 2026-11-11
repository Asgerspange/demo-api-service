"""Environment configuration (pydantic-settings) with fail-fast validation.

Field names map to UPPER_SNAKE env vars case-insensitively (db_host <- DB_HOST).
Local defaults match deploy/compose.dev.yml so `uv run` works with no .env.
In `production` (APP_ENV=production) the real secrets are required — startup
aborts with a clear message if any are missing or left at their placeholder.
"""
import sys

from pydantic import ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # dev | production
    app_env: str = "dev"

    # Database (Percona/MySQL) — defaults match deploy/compose.dev.yml
    db_host: str = "127.0.0.1"
    db_port: int = 3307
    db_user: str = "demoviewer"
    db_password: str = "devpass"
    db_name: str = "demoviewer"

    # Redis — the server's shared Redis over an SSH tunnel (deploy/redis-tunnel.sh).
    # demoviewer is isolated on logical db 3 (the Laravel apps use db 0/1).
    redis_url: str = "redis://127.0.0.1:6379/3"

    # bunny.net object storage
    bunny_demos_storage_key: str = ""
    bunny_demos_storage_host: str = "storage.bunnycdn.com"
    bunny_demos_cdn_host: str = ""
    bunny_demos_zone: str = "demos"
    # Cold tier: compressed raw .dem (cheapest archival). The warm canonical.zip lives in the
    # demos zone alongside the payloads — at $0.01/GB + light replication, a ~15 MB parquet
    # isn't worth a separate zone (Stage 10, revised for the real bunny setup).
    bunny_archive_storage_key: str = ""
    bunny_archive_zone: str = ""

    # External / auth
    steam_api_key: str = ""
    admin_token: str = "change-me"

    # Key auth (Stage 03)
    key_cache_ttl: int = 30                 # seconds to cache a key lookup in Redis
    key_rotation_grace_seconds: int = 86_400  # how long a rotated key stays valid
    client_default_rate_per_hour: int = 100   # default hourly limit for a new client key

    # Rate limiting (Stage 04)
    rate_limit_window_seconds: int = 3_600    # the "per hour" window

    # Content access control & anti-abuse (Stage 13)
    bunny_demos_token_key: str = ""           # pull-zone Token Authentication key (mints signed URLs)
    cdn_token_ttl: int = 3_600                # signed payload-URL lifetime (>= a practical session)
    bandwidth_cap_bytes: int = 0              # per-tenant payload bytes per window; 0 = unlimited
    bandwidth_window_seconds: int = 86_400    # bandwidth accounting window (daily)

    # Versions / limits
    api_version: str = "v1"
    payload_version: int = 1
    payload_gzip_level: int = 6               # per-round payload compression (1=fast..9=smallest)
    max_demo_bytes: int = 524_288_000

    # Ingestion (Stage 05)
    ingest_download_timeout: float = 120.0     # hard cap on a URL download (seconds)
    ingest_parse_timeout: float = 1_800.0      # hard cap on a single parse (seconds)
    ingest_zip_max_members: int = 64           # zip-bomb guard: reject archives with more
    ingest_round_upload_concurrency: int = 15  # bounded parallel per-round payload uploads
    ingest_rar_supported: bool = True          # rar/7z via libarchive (bsdtar); gated by its presence (Stage 18)
    ingest_steam_summaries: bool = False        # opt-in Steam player summaries (needs STEAM_API_KEY)
    # Cold-archive zstd level. Demos are high-entropy (~1.6x at any level), so the ultra
    # levels (19-22) cost minutes for ~nothing — a fast multithreaded level is the right call.
    ingest_archive_zstd_level: int = 10

    # Multi-tenancy & fairness (Stage 16)
    ingest_tenant_max_inflight: int = 3        # max concurrent parses per tenant (0 = no cap)
    ingest_defer_seconds: int = 5              # re-enqueue delay when a tenant is at its cap
    ingest_queue_depth_ceiling: int = 0        # backpressure: shed new ingests above this (0 = off)
    worker_queue: str = ""                     # which priority lane THIS worker pool drains (empty = standard)

    # Debug
    debug_demo_path: str | None = None

    @model_validator(mode="after")
    def _require_production_secrets(self) -> "Settings":
        """In production, secrets with no safe default must be set explicitly."""
        if self.app_env != "production":
            return self
        missing: list[str] = []
        if not self.bunny_demos_storage_key:
            missing.append("BUNNY_DEMOS_STORAGE_KEY")
        if not self.bunny_demos_cdn_host:
            missing.append("BUNNY_DEMOS_CDN_HOST")
        if not self.admin_token or self.admin_token == "change-me":
            missing.append("ADMIN_TOKEN (set a real secret, not the placeholder)")
        if missing:
            raise ValueError("missing required production config: " + ", ".join(missing))
        return self


def load_settings() -> Settings:
    """Load settings, failing fast with a readable message on misconfiguration."""
    try:
        return Settings()
    except ValidationError as exc:
        lines = [
            f"  - {'.'.join(str(p) for p in err['loc']) or 'config'}: {err['msg']}"
            for err in exc.errors()
        ]
        sys.stderr.write(
            "FATAL: invalid configuration (check your .env / environment):\n"
            + "\n".join(lines)
            + "\n"
        )
        raise SystemExit(1) from exc


settings = load_settings()
