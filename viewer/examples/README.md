# Reference proxies — CS Demoviewer "proxy mode"

The viewer always calls `{apiBase}{path}`. `apiBase` is either the **owner API** (direct
mode, with a client key) or **your backend** (proxy mode, no secret in the browser). Both
must implement the **identical** `/v1/**` path contract (Stage 06):

```
GET {apiBase}/v1/demos/{demoId}            -> demo metadata + round index
GET {apiBase}/v1/demos/{demoId}/rounds/{i} -> per-round payload (immutable bytes)
GET {apiBase}/v1/maps/{map}                -> calibration + radar URLs
```

## Direct mode (owner API + client key)

```js
CSDemoViewer.init({ el: '#v', demoId: 123,
  apiBase: 'https://api.owner.gg', clientKey: 'pk_live_…' });
```
The viewer sends `Authorization: Bearer pk_live_…`. The owner API verifies the key, checks
the **origin allowlist**, applies the **100/hr** limit, and serves.

## Proxy mode (your backend + server key)

```js
CSDemoViewer.init({ el: '#v', demoId: 123, apiBase: 'https://customer.com/cs' });
```
The browser sends **no secret**. Your backend forwards `/cs/v1/**` to the owner API and:

1. **Injects `X-Server-Key: sk_live_…`** server-side (never exposed to the browser).
2. **Injects `X-End-User: <stable user id>`** so the owner applies per-user limits keyed by
   `(server_key, end_user)`.
3. **Passes through** the owner's status, body, and `Cache-Control` / `ETag` /
   `Content-Encoding` / `X-RateLimit-*` headers **unchanged**.

### Contract requirements (a *transparent* passthrough)

- Only additions are the two `X-` headers and TLS termination.
- Do **not** rewrite paths beyond stripping your prefix (`/cs`).
- Do **not** buffer or transform bodies — binary payloads and gzip must pass through
  byte-for-byte (stream the response).
- Preserve caching headers so your own CDN/browser can cache immutable payloads.

### Implementations

- [`proxy.php`](proxy.php) — PHP / Laravel controller (`Route::any('/cs/{path}', …)`).
- [`proxy.js`](proxy.js) — Node / Express middleware on `/cs`.

Both read `CSVIEWER_API_BASE` and `CSVIEWER_SERVER_KEY` from config/env. The transparency
contract these implement is exercised in `api/tests/integration/test_proxy.py`.
