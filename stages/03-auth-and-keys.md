# Stage 03 — Auth, Keys & Admin

**Goal:** the key system and the owner-only admin to manage users and keys. Two key
kinds, two trust levels, plus origin-locking for the public client key.

## Context

The brief: *"a small interface where only I can create new users where they get a client
and a server key."* No public signup. Client key is exposed in the browser → it must be
domain-locked and rate-limited (Stage 04). Server key is backend-only → trusted, with
owner-set per-user limits.

## 3.1 Key model

Two kinds, Stripe-style:

| Kind | Prefix | Where it lives | Trust | Limit |
|------|--------|----------------|-------|-------|
| Client | `pk_live_…` | In the browser / viewer config | Low — public | Hard 100 req/hr/key + origin allowlist |
| Server | `sk_live_…` | Customer backend only | High | Owner-set per-end-user limits |

Rules:
- Generate keys as `prefix + base62(32 bytes)`. Store only `key_hash` (argon2id or
  sha256) + `last4` + `prefix`. Show the raw key **once** at creation.
- Verification: hash the presented key, look it up, check `status='active'`.
- **Client keys** additionally require the request `Origin`/`Referer` host to match one of
  `allowed_origins` (support `*.example.com` wildcards). Reject with 403 otherwise. This is
  what makes a public key safe to embed (gap #7 in Stage 00).
- **Server keys** must never be accepted on a request that came straight from a browser:
  treat `sk_` presented with a browser `Origin` as a misconfiguration → 400 with a clear
  message ("server keys must be used from your backend").
- Support **rotation** (issue new, keep old active for a grace window) and **revocation**
  (immediate). Cache key lookups in Redis with short TTL + revocation busting.

## 3.2 How keys reach the API

- Direct mode (client key): header `Authorization: Bearer pk_live_…` (also accept
  `X-Client-Key`). CORS is evaluated against the key's `allowed_origins`.
- Proxy mode (server key): header `X-Server-Key: sk_live_…` set by the customer backend,
  plus `X-End-User: <opaque-id>` to attribute per-user limits (Stage 04). Never set by a
  browser.

## 3.3 Auth dependency

Build a FastAPI dependency `authenticate()` in `app/auth/` that:
1. Detects key kind from prefix.
2. Verifies hash + status (Redis-cached).
3. For client keys: enforces origin allowlist; sets `ctx.subject = key`, `ctx.limit_scope =
   ("client_key", key_id)`.
4. For server keys: requires `X-End-User`; sets `ctx.limit_scope = ("server_user", key_id,
   end_user)` and the owner-configured per-user `rate_per_hour`.
5. Returns an `AuthContext` consumed by the rate limiter (Stage 04) and routers.

## 3.4 Admin interface (owner only)

A minimal authenticated surface — **single super-admin**, not a user-facing system:
- Auth via a strong static admin token (env) or a simple owner login; lock to your IP if
  possible. Keep it boring and out of the public router tree (`/admin`, separate auth).
- Endpoints:
  - `POST /admin/users` → create user.
  - `POST /admin/users/{id}/keys` → issue a client or server key (returns raw key once).
  - `PATCH /admin/keys/{id}` → set `allowed_origins`, `rate_per_hour`, rotate, revoke.
  - `GET /admin/users` / `GET /admin/usage` → list users, recent usage (from Redis/rollups).
- A tiny static HTML page (served by the API or shipped separately) that calls these — no
  framework needed. This is the "small interface" from the brief.

## Reuse from existing code

- `useApi.ts` → client patterns if you build the admin page with a fetch wrapper.
- Nothing security-sensitive from the old app should be copied verbatim; the old app used
  Laravel session/team auth which we are intentionally replacing.

## Acceptance criteria

- **Tests (required for Done):** the tests this phase needs are written and green in CI — see
  `TESTING.md` for stack/layout and its per-phase table for exactly what to cover.

- Owner can create a user and issue both key kinds via `/admin`; raw key shown once.
- A client key works only from an allowlisted origin; wrong origin → 403.
- A server key presented with a browser `Origin` → 400; from backend with `X-End-User` → ok.
- Revoked key → 401 within the cache TTL window; rotation keeps the old key valid for the
  configured grace period.
- Admin endpoints are unreachable without the admin credential.
