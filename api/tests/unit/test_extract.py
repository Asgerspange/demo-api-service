"""Stage 05 — magic-byte format detection + decompression guards (security-required)."""
import bz2
import gzip
import io
import subprocess
import zipfile

import pytest

from app.ingest.errors import ExtractError, TooLargeError, UnsupportedDemoError
from app.ingest.extract import detect_format, extract_dem, extract_dems, have_libarchive

pytestmark = pytest.mark.unit

CS2 = b"PBDEMS2\x00" + b"democontent" * 100
CS2_B = b"PBDEMS2\x00" + b"othercontent" * 80
CSGO = b"HL2DEMO\x00" + b"oldcontent" * 100


def _zip_with(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_detect_format():
    assert detect_format(CS2) == "dem"
    assert detect_format(CSGO) == "dem"
    assert detect_format(gzip.compress(CS2)) == "gzip"
    assert detect_format(bz2.compress(CS2)) == "bzip2"
    assert detect_format(_zip_with({"a.dem": CS2})) == "zip"
    assert detect_format(b"Rar!\x1a\x07\x00rar") == "rar"
    assert detect_format(b"random junk") == "unknown"


def test_extract_plain_dem():
    assert extract_dem(CS2, max_bytes=10_000) == CS2


def test_extract_gzip():
    assert extract_dem(gzip.compress(CS2), max_bytes=10_000) == CS2


def test_extract_bzip2():
    # Valve matchmaking / Steam match-sharing demos ship as .dem.bz2.
    assert extract_dem(bz2.compress(CS2), max_bytes=10_000) == CS2


def test_extract_zip_single_member():
    assert extract_dem(_zip_with({"match.dem": CS2}), max_bytes=10_000) == CS2


def test_extract_rejects_csgo():
    with pytest.raises(UnsupportedDemoError, match="CS2"):
        extract_dem(CSGO, max_bytes=10_000)
    with pytest.raises(UnsupportedDemoError):
        extract_dem(gzip.compress(CSGO), max_bytes=10_000)


def test_rar_rejected_when_libarchive_disabled():
    # With rar extraction turned off, a .rar is cleanly rejected (the pre-Stage-18 behavior).
    with pytest.raises(UnsupportedDemoError, match="rar"):
        extract_dems(b"Rar!\x1a\x07\x00" + b"x" * 50, max_bytes=10_000, allow_rar=False)


def test_extract_rejects_unknown():
    with pytest.raises(ExtractError):
        extract_dem(b"not a demo at all", max_bytes=10_000)


def test_extract_rejects_non_dem_gzip():
    with pytest.raises(ExtractError):
        extract_dem(gzip.compress(b"just some text, not a demo"), max_bytes=10_000)


def test_zip_bomb_too_many_members():
    bomb = _zip_with({f"f{i}.dem": CS2 for i in range(5)})
    with pytest.raises((TooLargeError, ExtractError)):
        extract_dem(bomb, max_bytes=10_000, max_members=3)


def test_zip_no_dem_member():
    with pytest.raises(ExtractError, match="no .dem"):
        extract_dem(_zip_with({"readme.txt": b"hello"}), max_bytes=10_000)


def test_extract_dem_singular_rejects_multi_demo_archive():
    # The back-compat single-demo helper refuses a multi-demo archive (callers use extract_dems).
    z = _zip_with({"a.dem": CS2, "b.dem": CS2_B})
    with pytest.raises(ExtractError, match="multi-demo"):
        extract_dem(z, max_bytes=100_000)


def test_extract_dems_returns_all_demos_in_a_zip():
    # An HLTV-style multi-map archive → one Extracted per .dem (Stage 18 §18.1).
    z = _zip_with({"de_nuke.dem": CS2, "de_mirage.dem": CS2_B, "readme.txt": b"ignore me"})
    dems = extract_dems(z, max_bytes=100_000)
    assert {d.name for d in dems} == {"de_nuke.dem", "de_mirage.dem"}
    assert {bytes(d.data) for d in dems} == {CS2, CS2_B}


def test_extract_dems_reassembles_split_parts_in_a_zip():
    # A single demo split into parts inside the archive → one reassembled demo (§18.2).
    head = b"PBDEMS2\x00" + b"head" * 50
    tail = b"tailtail" * 50
    z = _zip_with({"match_p1.dem": head, "match_p2.dem": tail})
    dems = extract_dems(z, max_bytes=100_000)
    assert len(dems) == 1
    assert bytes(dems[0].data) == head + tail


def test_extract_dems_single_dem_is_one_element_list():
    dems = extract_dems(CS2, max_bytes=10_000)
    assert len(dems) == 1 and bytes(dems[0].data) == CS2


def test_zip_member_over_cap():
    big = b"PBDEMS2\x00" + b"x" * 50_000
    with pytest.raises(TooLargeError):
        extract_dem(_zip_with({"a.dem": big}), max_bytes=10_000)


def test_gzip_bomb_over_cap():
    big = b"PBDEMS2\x00" + b"0" * 200_000
    with pytest.raises(TooLargeError):
        extract_dem(gzip.compress(big), max_bytes=10_000)


def test_bzip2_bomb_over_cap():
    big = b"PBDEMS2\x00" + b"0" * 200_000
    with pytest.raises(TooLargeError):
        extract_dem(bz2.compress(big), max_bytes=10_000)


def test_extract_rejects_non_dem_bzip2():
    with pytest.raises(ExtractError):
        extract_dem(bz2.compress(b"just some text, not a demo"), max_bytes=10_000)


@pytest.mark.skipif(not have_libarchive(), reason="libarchive (bsdtar) not installed")
def test_libarchive_extracts_multi_demo_archive(tmp_path):
    # Real libarchive path via a .7z bsdtar can create (RAR is read-only in libarchive; 7z exercises
    # the identical extraction code). Confirms multi-demo archives extract via the §18.1 path.
    (tmp_path / "de_nuke.dem").write_bytes(CS2)
    (tmp_path / "de_mirage.dem").write_bytes(CS2_B)
    archive = tmp_path / "match.7z"
    subprocess.run(["bsdtar", "-a", "-cf", str(archive), "-C", str(tmp_path),
                    "de_nuke.dem", "de_mirage.dem"], check=True)
    data = archive.read_bytes()
    assert detect_format(data) == "7z"
    dems = extract_dems(data, max_bytes=100_000, allow_rar=True)
    assert {d.name for d in dems} == {"de_nuke.dem", "de_mirage.dem"}
    assert {bytes(d.data) for d in dems} == {CS2, CS2_B}


@pytest.mark.skipif(not have_libarchive(), reason="libarchive (bsdtar) not installed")
def test_libarchive_archive_rejected_when_disabled(tmp_path):
    (tmp_path / "a.dem").write_bytes(CS2)
    archive = tmp_path / "x.7z"
    subprocess.run(["bsdtar", "-a", "-cf", str(archive), "-C", str(tmp_path), "a.dem"], check=True)
    with pytest.raises(UnsupportedDemoError):
        extract_dems(archive.read_bytes(), max_bytes=100_000, allow_rar=False)
