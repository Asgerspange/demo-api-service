"""Reassemble multi-part demos (Stage 18 §18.2).

Some sources split a single demo into part files — `match_p1.dem`, `match_p2.dem`, … (HLTV-style
byte continuations). We detect a `_pN` / `.partN` / `-pN` suffix, group files sharing a base name,
sort by part number, and concatenate them into one logical `.dem`. Only the first part carries the
`PBDEMS2` header, so the caller validates the *reassembled whole*, not each part.

Pure (no I/O) so the grouping/ordering is unit-tested. A file with no part suffix — or a base with
only one part — passes through unchanged (a lone `*_p1.dem` is just one demo, not a fragment).
"""
from __future__ import annotations

import re

# Stem (no dir, no `.dem`) ending in a part marker: `_p1`, `-p02`, `.part3`, `_part10`.
_PART_RE = re.compile(r"^(?P<base>.+?)[._-]p(?:art)?[._-]?(?P<n>\d+)$", re.IGNORECASE)


def _stem(name: str) -> str:
    """Filename without any directory prefix or a trailing `.dem` (case-insensitive)."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    return base[:-4] if base.lower().endswith(".dem") else base


def parse_part(name: str) -> tuple[str, int] | None:
    """`('match', 2)` if `name` looks like a demo part, else None."""
    m = _PART_RE.match(_stem(name))
    if not m:
        return None
    return m.group("base"), int(m.group("n"))


def reassemble(members: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    """Collapse part files into whole demos. Input/output are `(name, bytes)` lists.

    Files with the same base and ≥2 parts are concatenated in part-number order into one
    `<base>.dem`. Everything else (including a lone `*_p1.dem`) passes through unchanged. Output
    order is stable: non-part files keep their input order; each reassembled group appears at the
    position of its first-seen part.
    """
    order: list[str] = []                       # keys in first-seen order
    bucket: dict[str, list[tuple[int, str, bytes]]] = {}
    singles: dict[str, tuple[str, bytes]] = {}   # key → (name, data) for non-grouped entries

    for idx, (name, data) in enumerate(members):
        pp = parse_part(name)
        if pp is None:
            key = f"__single__{idx}"
            singles[key] = (name, data)
            order.append(key)
            continue
        base, n = pp
        if base not in bucket:
            bucket[base] = []
            order.append(base)
        bucket[base].append((n, name, data))

    out: list[tuple[str, bytes]] = []
    for key in order:
        if key in singles:
            out.append(singles[key])
            continue
        parts = sorted(bucket[key], key=lambda t: t[0])
        if len(parts) == 1:
            # a single part is just a whole demo (keep its original name)
            out.append((parts[0][1], parts[0][2]))
        else:
            joined = b"".join(p[2] for p in parts)
            out.append((f"{key}.dem", joined))
    return out
