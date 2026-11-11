"""Ingestion error types.

`IngestError` carries a stable `code` so the job's `error` field and the (future) webhook
payload describe *why* an ingest failed in a machine-readable way. `client_safe` errors are
caused by the submitted source (bad URL, non-demo, unsupported codec) and are surfaced to the
caller verbatim; non-client errors are internal failures.
"""
from __future__ import annotations


class IngestError(Exception):
    """Base class for an ingestion failure with a stable error code."""

    code = "ingest_error"
    client_safe = True

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SSRFError(IngestError):
    """The download URL resolves to a blocked (private/loopback/metadata) host or redirects."""

    code = "ssrf_blocked"


class DownloadError(IngestError):
    """The source could not be fetched (network, status, or size-cap)."""

    code = "download_failed"


class TooLargeError(DownloadError):
    """The download (or a decompressed member) exceeded the configured size cap."""

    code = "too_large"


class ExtractError(IngestError):
    """The bytes could not be decompressed/extracted to a single `.dem`."""

    code = "extract_failed"


class UnsupportedDemoError(IngestError):
    """The file is a demo but not a supported one (CSGO/source1, or an unsupported codec)."""

    code = "unsupported_demo"
