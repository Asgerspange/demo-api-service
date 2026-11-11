"""Phase 01 — config fail-fast validation."""
import pytest
from pydantic import ValidationError

from app.config import Settings


@pytest.mark.unit
def test_dev_loads_with_defaults():
    s = Settings(_env_file=None)
    assert s.app_env == "dev"
    assert s.db_port == 3307


@pytest.mark.unit
def test_production_missing_secrets_raises():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="production",
            admin_token="change-me",  # placeholder is rejected
            bunny_demos_storage_key="",
            bunny_demos_cdn_host="",
        )


@pytest.mark.unit
def test_production_with_secrets_loads():
    s = Settings(
        _env_file=None,
        app_env="production",
        bunny_demos_storage_key="k",
        bunny_demos_cdn_host="demos.b-cdn.net",
        admin_token="real-secret",
    )
    assert s.app_env == "production"
