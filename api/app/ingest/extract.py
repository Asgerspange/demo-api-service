"""Decompress/extract an acquired blob to CS2 `.dem` bytes (Stage 5.2 step 2 / Stage 18).

Format is detected by **magic bytes**, never by extension (the URL/extension is untrusted):
- `.dem`  → CS2 demos start with `PBDEMS2`; CSGO/source1 demos start with `HL2DEMO` and are
  rejected here (CS2-only).
- `.gz`   → gzip stream → inner bytes must be a CS2 `.dem`.
- `.bz2`  → bzip2 stream → inner bytes must be a CS2 `.dem` (Valve matchmaking/Steam
  match-sharing demos ship as `.dem.bz2`).
- `.zip`  → may contain **several** `.dem` members (an HLTV match = one per map, Stage 18); zip-bomb
  guarded (member count + declared uncompressed sizes) and path-traversal-safe (members are read by
  name into memory, never extracted to disk).
- `.rar`/`.7z` → extracted via **libarchive** (`bsdtar`, BSD-licensed, reads RAR4/5) when present —
  HLTV ships matches as `.rar` (Stage 18 §18.1). If libarchive isn't installed, cleanly rejected.

`extract_dems()` returns **all** contained demos (after multi-part reassembly, §18.2);
`extract_dem()` keeps the old single-demo contract for callers that want exactly one.
"""
from __future__ import annotations

import io
import bz2
import gzip
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass

from ..config import settings
from .errors import ExtractError, TooLargeError, UnsupportedDemoError
from .parts import reassemble

# Magic bytes.
GZIP_MAGIC = b"\x1f\x8b"
BZIP2_MAGIC = b"BZh"
ZIP_MAGIC = b"PK\x03\x04"
RAR_MAGIC = b"Rar!\x1a\x07"
SEVENZ_MAGIC = b"7z\xbc\xaf\x27\x1c"
CS2_DEM_MAGIC = b"PBDEMS2"   # source2 / CS2
CSGO_DEM_MAGIC = b"HL2DEMO"  # source1 / CSGO (rejected)


@dataclass(frozen=True)
class Extracted:
    """One demo pulled from a container: its in-archive name + validated CS2 `.dem` bytes."""
    name: str
    data: bytes


def detect_format(data: bytes) -> str:
    """Classify the container by leading bytes: 'dem'|'gzip'|'zip'|'rar'|'7z'|'unknown'."""
    if data[:7] == CS2_DEM_MAGIC or data[:7] == CSGO_DEM_MAGIC:
        return "dem"
    if data[:2] == GZIP_MAGIC:
        return "gzip"
    if data[:3] == BZIP2_MAGIC:
        return "bzip2"
    if data[:4] == ZIP_MAGIC:
        return "zip"
    if data[:6] == RAR_MAGIC:
        return "rar"
    if data[:6] == SEVENZ_MAGIC:
        return "7z"
    return "unknown"


def _assert_cs2_dem(data: bytes) -> bytes:
    """Validate bytes are a CS2 `.dem`; reject CSGO/source1 and non-demos."""
    if data[:7] == CSGO_DEM_MAGIC:
        raise UnsupportedDemoError("CSGO/source1 demos are not supported (CS2 only)")
    if data[:7] != CS2_DEM_MAGIC:
        raise ExtractError("decompressed content is not a CS2 .dem (bad magic bytes)")
    return data


def _gunzip(data: bytes, *, max_bytes: int) -> bytes:
    """Decompress a gzip stream with a hard output cap (decompression-bomb guard)."""
    out = io.BytesIO()
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
            while True:
                chunk = gz.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                if out.tell() > max_bytes:
                    raise TooLargeError(
                        f"gzip expands past the {max_bytes} byte cap (decompression bomb?)"
                    )
    except (OSError, EOFError) as exc:
        if isinstance(exc, TooLargeError):
            raise
        raise ExtractError(f"could not gunzip source: {exc}") from exc
    return out.getvalue()


def _bunzip2(data: bytes, *, max_bytes: int) -> bytes:
    """Decompress a bzip2 stream with a hard output cap (decompression-bomb guard)."""
    out = io.BytesIO()
    try:
        with bz2.BZ2File(io.BytesIO(data)) as bz:
            while True:
                chunk = bz.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                if out.tell() > max_bytes:
                    raise TooLargeError(
                        f"bzip2 expands past the {max_bytes} byte cap (decompression bomb?)"
                    )
    except (OSError, EOFError) as exc:
        if isinstance(exc, TooLargeError):
            raise
        raise ExtractError(f"could not bunzip2 source: {exc}") from exc
    return out.getvalue()


def _is_dem_name(name: str) -> bool:
    """A `.dem` (whole or a `_pN` part) member — directories/other files are ignored."""
    return name.lower().endswith(".dem") and not name.endswith("/")


def _unzip_all(data: bytes, *, max_bytes: int, max_members: int) -> list[tuple[str, bytes]]:
    """Extract every `.dem` member's RAW bytes from a zip, guarded against bombs + traversal.

    Returns `(name, bytes)` pairs (NOT yet CS2-validated — part files are validated only after
    reassembly). The bytes are read by member name into memory, so member names can't traverse.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ExtractError(f"corrupt zip archive: {exc}") from exc

    out: list[tuple[str, bytes]] = []
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > max_members:
            raise TooLargeError(
                f"zip has {len(infos)} members (> {max_members}); refusing (zip bomb?)"
            )
        if sum(i.file_size for i in infos) > max_bytes:
            raise TooLargeError(
                f"zip declares > {max_bytes} uncompressed bytes (decompression bomb?)"
            )
        dem_members = [i for i in infos if _is_dem_name(i.filename)]
        if not dem_members:
            raise ExtractError("zip contains no .dem member")
        for member in dem_members:
            if member.file_size > max_bytes:
                raise TooLargeError(
                    f"zip member {member.filename!r} is {member.file_size} bytes (> {max_bytes} cap)"
                )
            with zf.open(member) as fp:
                blob = fp.read(max_bytes + 1)
            if len(blob) > max_bytes:
                raise TooLargeError("zip member exceeded the size cap while reading")
            out.append((member.filename, blob))
    return out


def have_libarchive() -> bool:
    """True if `bsdtar` (libarchive) is available to extract rar/7z (Stage 18 §18.1)."""
    return shutil.which("bsdtar") is not None


def _libarchive_all(data: bytes, fmt: str, *, max_bytes: int,
                    max_members: int) -> list[tuple[str, bytes]]:
    """Extract every `.dem` member from a rar/7z via libarchive (`bsdtar`), bomb/traversal-guarded.

    Entries are streamed to stdout by exact name (`bsdtar -xOf`), never written to disk, so member
    names can't traverse. The archive is listed first to enforce the member-count cap; each entry
    read is capped at `max_bytes`.
    """
    if not have_libarchive():
        raise UnsupportedDemoError(
            f"{fmt} archives need libarchive (bsdtar), which isn't installed; "
            "re-upload the demo as .dem, .gz, or .zip"
        )
    with tempfile.NamedTemporaryFile(suffix=f".{fmt}") as tf:
        tf.write(data)
        tf.flush()
        try:
            listing = subprocess.run(
                ["bsdtar", "-tf", tf.name], capture_output=True, timeout=60, check=True)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise ExtractError(f"could not read {fmt} archive: {exc}") from exc

        names = [n for n in listing.stdout.decode("utf-8", "replace").splitlines() if n]
        if len(names) > max_members:
            raise TooLargeError(
                f"{fmt} has {len(names)} members (> {max_members}); refusing (archive bomb?)"
            )
        dem_names = [n for n in names if _is_dem_name(n)]
        if not dem_names:
            raise ExtractError(f"{fmt} archive contains no .dem member")

        out: list[tuple[str, bytes]] = []
        for name in dem_names:
            try:
                res = subprocess.run(
                    ["bsdtar", "-xOf", tf.name, "--", name],
                    capture_output=True, timeout=120, check=True)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                raise ExtractError(f"could not extract {name!r} from {fmt}: {exc}") from exc
            blob = res.stdout
            if len(blob) > max_bytes:
                raise TooLargeError(
                    f"{fmt} member {name!r} exceeds the {max_bytes} byte cap (bomb?)"
                )
            out.append((name, blob))
        return out


def extract_dems(data: bytes, *, max_bytes: int, max_members: int = 64,
                 allow_rar: bool | None = None) -> list[Extracted]:
    """Return every CS2 `.dem` in an acquired blob (Stage 18): handles plain/gz demos, multi-demo
    zip/rar/7z archives, and multi-part (`_pN`) reassembly. Each returned demo is CS2-validated.

    `allow_rar` gates libarchive extraction (rar/7z); None → `settings.ingest_rar_supported`.
    """
    if allow_rar is None:
        allow_rar = settings.ingest_rar_supported
    fmt = detect_format(data)

    if fmt == "dem":
        return [Extracted("demo.dem", _assert_cs2_dem(data))]
    if fmt == "gzip":
        return [Extracted("demo.dem", _assert_cs2_dem(_gunzip(data, max_bytes=max_bytes)))]
    if fmt == "bzip2":
        return [Extracted("demo.dem", _assert_cs2_dem(_bunzip2(data, max_bytes=max_bytes)))]

    if fmt == "zip":
        members = _unzip_all(data, max_bytes=max_bytes, max_members=max_members)
    elif fmt in ("rar", "7z"):
        if not allow_rar:
            raise UnsupportedDemoError(
                f"{fmt} archives are not enabled; re-upload the demo as .dem, .gz, or .zip"
            )
        members = _libarchive_all(data, fmt, max_bytes=max_bytes, max_members=max_members)
    elif fmt == "unknown":
        raise ExtractError("unrecognized file format (not a .dem/.gz/.zip/.rar/.7z)")
    else:  # pragma: no cover — exhaustive
        raise ExtractError(f"unhandled format {fmt!r}")

    # Multi-part reassembly (§18.2), then validate each whole demo (only part 1 carries the header).
    wholes = reassemble(members)
    if not wholes:
        raise ExtractError("archive contained no usable .dem after reassembly")
    return [Extracted(name, _assert_cs2_dem(blob)) for name, blob in wholes]


def extract_dem(data: bytes, *, max_bytes: int, max_members: int = 64) -> bytes:
    """Back-compat single-demo extraction: the validated CS2 `.dem` bytes, requiring exactly one.

    Multi-demo archives raise — callers wanting the whole match use `extract_dems()`.
    """
    dems = extract_dems(data, max_bytes=max_bytes, max_members=max_members)
    if len(dems) > 1:
        raise ExtractError(
            f"archive contains {len(dems)} demos; use multi-demo ingest (extract_dems)"
        )
    return dems[0].data
