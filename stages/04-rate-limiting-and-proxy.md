# Stage 04 — Rate Limiting & the Proxy Contract

**Goal:** enforce the two limit regimes and define the exact proxy pattern so the viewer
can talk to either the owner API or a customer's backend without code changes.

## Context

Brief: *"direct with client token → 100 req/hr; proxied through their backend with server
key → owner-settable per-user limits. The viewer must handle direct IP to me or to their
own proxy following a pattern we define."*

## 4.1 Rate limiting (Redis)

Use a **sliding-window** counter in Redis (atomic via Lua or `INCR`+`EXPIRE` per window
bucket). Keying by limit scope from the `AuthContext` (Stage 03):

| Scope | Key | Limit |
|-------|-----|-------|
| Client key (direct) | `rl:ck:{key_id}` | 100 / hour (hard, from brief) |
| Server-key end-user (proxy) | `rl:su:{key_id}:{end_user}` | owner-set `rate_per_hour` on the key (or a per-user override table) |

Behavior:
- On limit exceed → `429` with `Retry-After` and `X-RateLimit-{Limit,Remaining,Reset}`
  headers (set them on every response, not just 429).
- Make the limiter a FastAPI dependency that runs after `authenticate()`.
- Counters are cheap and ephemeral; optionally roll daily totals into a `usage` table for
  billing/inspection in the admin.
- Burst protection: also cap concurrent in-flight per scope (small semaphore) so a single
  key can't fan out 100 simultaneous heavy reads.

## 4.2 The proxy contract (the "pattern we define")

The viewer always calls `{apiBase}{path}`. `apiBase` is either the owner API or the
customer's proxy. **Both must implement the identical path contract** (defined fully in
Stage 06):

```
GET  {apiBase}/v1/demos/{demoId}                 -> demo metadata + round index
GET  {apiBase}/v1/demos/{demoId}/rounds/{i}      -> per-round payload (immutable)
GET  {apiBase}/v1/maps/{map}                      -> scale + radar URLs
```

### Direct mode (owner API, client key)
- Viewer sends `Authorization: Bearer pk_live_…`.
- Owner API: verify client key → check origin allowlist → 100/hr limit → serve.

### Proxy mode (customer backend, server key)
- Viewer sends **no secret**; `apiBase` points at the customer's proxy, e.g.
  `https://customer.com/cs`.
- The customer proxy MUST:
  1. Forward the same path under its base to the owner API, i.e.
     `GET https://api.owner.gg/v1/demos/123` ⇽ `GET https://customer.com/cs/v1/demos/123`.
  2. Inject `X-Server-Key: sk_live_…` server-side (never exposed to the browser).
  3. Inject `X-End-User: <their stable user id>` so the owner can apply per-user limits.
  4. Pass through the owner API's status code, body, and the `Cache-Control`/`ETag`/
     `X-RateLimit-*` headers unchanged.
- The owner API: verify server key → require `X-End-User` → apply that key's per-user
  limit keyed by `(key_id, end_user)` → serve.

**Contract requirement:** the proxy must be a *transparent passthrough* of `/v1/**`. The
only things it adds are the two `X-` headers and TLS termination. It must not rewrite paths
beyond prefixing, must not buffer/transform bodies (so binary payloads + gzip pass through),
and should preserve caching headers so its own CDN/browser can cache immutable payloads.

### Reference proxies (ship these in `viewer/examples/` and docs)

PHP / Laravel (matches the customer's likely stack — they came from Laravel):
```php
// routes/web.php  — Route::any('/cs/{path}', ProxyController::class)->where('path','.*');
public function __invoke(Request $req, string $path) {
    $resp = Http::withHeaders([
        'X-Server-Key' => config('services.csviewer.server_key'),
        'X-End-User'   => (string)($req->user()?->id ?? 'anon'),
    ])->withOptions(['stream' => true])
      ->get("https://api.owner.gg/{$path}", $req->query());
    return response($resp->body(), $resp->status())
        ->withHeaders($resp->headers());   // preserve Cache-Control/ETag/Content-Encoding
}
```

Node / Express:
```js
app.use('/cs', (req, res) => {
  const url = `https://api.owner.gg${req.originalUrl.replace(/^\/cs/, '')}`;
  fetch(url, { headers: {
    'X-Server-Key': process.env.CSVIEWER_SERVER_KEY,
    'X-End-User': String(req.user?.id ?? 'anon'),
  }}).then(async r => {
    r.headers.forEach((v, k) => res.setHeader(k, v));   // preserve caching headers
    res.status(r.status);
    Readable.fromWeb(r.body).pipe(res);                 // stream, no buffering
  });
});
```

## 4.3 Viewer-side config (defines how it "handles direct or proxy")

```js
// direct
CSDemoViewer.init({ el: '#v', demoId: 123,
  apiBase: 'https://api.owner.gg', clientKey: 'pk_live_…' });
// proxy (no secret in browser)
CSDemoViewer.init({ el: '#v', demoId: 123,
  apiBase: 'https://customer.com/cs' });
```
The viewer only branches on "is `clientKey` set?" → send `Authorization` or not. Everything
else (paths, parsing, caching) is identical. Detailed in Stage 07.

## Reuse from existing code

- `CacheService.php` → the old caching intent; reimplement as Redis + HTTP cache headers.
- `RoundLoader.worker.js` `baseUrl` handling → the viewer already supports a configurable
  base URL; generalize it to `apiBase`.

## Acceptance criteria

- **Tests (required for Done):** the tests this phase needs are written and green in CI — see
  `TESTING.md` for stack/layout and its per-phase table for exactly what to cover.

- 101st client-key request within an hour → 429 with correct `Retry-After`.
- Server-key requests are limited per `X-End-User`; two different end-users don't share a
  bucket; missing `X-End-User` → 400.
- `X-RateLimit-*` headers present on success responses.
- A working PHP and Node reference proxy that passes `/v1/**` through transparently,
  including `Content-Encoding`/`ETag`/`Cache-Control`.
