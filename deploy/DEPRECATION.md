# Versioning & Deprecation Policy (Stage 17 §17.5)

Embedded viewers live on third-party sites we **cannot force-update**. So both the API surface and
the per-round payload format are versioned, and old versions are supported for a published window.

## What's versioned

- **`/v1` API** — the serving contract (`/v1/demos/{id}`, `/rounds/{i}`, `/maps`). A breaking change
  ships under `/v2`; `/v1` keeps working until its sunset.
- **`payload_version`** — the per-round wire format. Each demo declares its version in
  `/v1/demos/{id}` and stores payloads under `…/v{N}/round-{i}.bin`, so multiple versions coexist.
  The viewer reads the version and decodes accordingly (`negotiatePayloadVersion` in `src/version.js`).
- **Viewer bundle** — published immutably at `viewer/v{semver}/viewer.js` (Stage 09). A host pins a
  version; `latest` tracks the newest.

## Support window

- Each `payload_version` and each `/v{n}` API is supported for **at least 12 months** after its
  successor ships, with the **sunset date published here** before removal.
- During that window the API keeps serving the old payloads unchanged; a viewer pinned to the old
  format keeps working. A backfill (Stage 14) migrates the library to the new format *alongside* the
  old one — the old objects are GC'd only after the sunset.

## What the viewer does

- Decodes whatever `payload_version` a demo declares, if its bundle supports it
  (`SUPPORTED_PAYLOAD_VERSIONS`).
- Emits a **console warning** (and an `onDeprecation` hook) when a host is pinned to a payload
  version near end-of-life, naming the sunset date — so integrators update before removal.
- Shows a clear "update the embed" message (never a blank/broken render) if a demo's version is
  outside what the pinned bundle can decode.

## Current status

| Version | Status | Sunset |
|---|---|---|
| API `/v1` | **current** | — |
| `payload_version` 1 | **current** | — |

(When `payload_version` 2 ships, mark v1 *deprecated* here with its sunset date and add it to
`DEPRECATED_PAYLOAD_VERSIONS` in `viewer/src/version.js`.)
