"""Load the Stage 15 corpus manifest + its recorded fixtures and golden snapshots.

The corpus is **version-controlled as pointers + ground truth** (the demos themselves are large
and live in cold object storage; `storage_ref` is the key). Each entry may carry a committed
*recorded fixture* — the sanitized structured outputs a real ingest produced — from which the
golden snapshot is derived. Entries without a recorded fixture are still asserted to *cover* the
Stage 11 cases + map matrix; their golden gate runs in the `slow` path against the real `.dem`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = CORPUS_DIR / "manifest.json"
RECORDED_DIR = CORPUS_DIR / "recorded"
GOLDEN_DIR = CORPUS_DIR / "golden"

# The active-duty map pool the corpus matrix must cover (mirrors the map_metadata seed; kept
# here so the regression test fails loudly if the pool and the corpus drift apart).
ACTIVE_DUTY_MAPS = {
    "de_ancient", "de_anubis", "de_cache", "de_dust2",
    "de_inferno", "de_mirage", "de_nuke", "de_overpass",
}

# Every Stage 11 real-world case the corpus must exercise (§15.1).
REQUIRED_CASES = {
    "gotv", "128tick", "pro", "overtime", "pov", "truncated", "disconnect",
    "reworked_map", "unknown_map",
}


@dataclass(frozen=True)
class CorpusEntry:
    slug: str
    description: str
    map: str | None
    cases: tuple[str, ...]
    storage_ref: str | None
    recorded: bool
    ground_truth: dict

    @property
    def recorded_path(self) -> Path:
        return RECORDED_DIR / f"{self.slug}.json"

    def golden_path(self, payload_version: int) -> Path:
        return GOLDEN_DIR / f"v{payload_version}" / f"{self.slug}.json"

    def load_recorded(self) -> dict:
        return json.loads(self.recorded_path.read_text(encoding="utf-8"))

    def load_golden(self, payload_version: int) -> dict:
        return json.loads(self.golden_path(payload_version).read_text(encoding="utf-8"))


def load_manifest() -> list[CorpusEntry]:
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return [
        CorpusEntry(
            slug=e["slug"],
            description=e.get("description", ""),
            map=e.get("map"),
            cases=tuple(e.get("cases", [])),
            storage_ref=e.get("storage_ref"),
            recorded=bool(e.get("recorded", False)),
            ground_truth=e.get("ground_truth", {}),
        )
        for e in raw["demos"]
    ]


def recorded_entries() -> list[CorpusEntry]:
    """Entries with a committed recorded fixture — the ones the fast golden gate runs over."""
    return [e for e in load_manifest() if e.recorded]
