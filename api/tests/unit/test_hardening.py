"""Stage 08 §8.2 — security hardening guards (the audit, as enforceable tests)."""
import io
import zipfile
from pathlib import Path

import pytest

from app.ingest.errors import ExtractError
from app.ingest.extract import extract_dem

pytestmark = pytest.mark.unit

APP_DIR = Path(__file__).resolve().parents[2] / "app"
CS2 = b"PBDEMS2\x00" + b"x" * 500


def test_no_tls_verification_disabled_anywhere():
    """The old Steam call used `verify=False`; that must never reappear (no disabled TLS)."""
    offenders = []
    for py in APP_DIR.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        if "verify=False" in text or "verify = False" in text:
            offenders.append(str(py))
    assert offenders == [], f"TLS verification disabled in: {offenders}"


def test_zip_path_traversal_member_is_not_written_to_disk(tmp_path):
    """A zip whose .dem member name escapes the dir must not traverse — we read the member
    by name into memory (never extract to disk), so a `../` name can't write outside."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../../../etc/evil.dem", CS2)
    # It still extracts the bytes (single .dem member) but writes nothing to the filesystem.
    out = extract_dem(buf.getvalue(), max_bytes=10_000)
    assert out == CS2
    assert not (tmp_path / "etc").exists()
    assert not Path("/tmp/etc/evil.dem").exists()


def test_absolute_path_member_name_is_safe():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("/abs/evil.dem", CS2)
    assert extract_dem(buf.getvalue(), max_bytes=10_000) == CS2  # read in-memory, no disk write


def test_non_dem_zip_rejected_without_extraction():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("payload.sh", b"#!/bin/sh\nrm -rf /\n")
    with pytest.raises(ExtractError):
        extract_dem(buf.getvalue(), max_bytes=10_000)
