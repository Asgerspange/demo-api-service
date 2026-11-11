"""The AuthContext produced by `authenticate()` and consumed by routers + the rate
limiter (Stage 04).

`limit_scope` is the tuple the limiter buckets on:
- client key:  ("client_key", key_id)            — one bucket per key
- server key:  ("server_user", key_id, end_user) — one bucket per (key, end-user)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthContext:
    key_id: int
    user_id: int
    kind: str                       # 'client' | 'server'
    rate_per_hour: int | None
    end_user: str | None = None     # set for server keys (from X-End-User)

    @property
    def limit_scope(self) -> tuple:
        if self.kind == "server":
            return ("server_user", self.key_id, self.end_user)
        return ("client_key", self.key_id)
