#!/usr/bin/env bash
# Build + publish the viewer bundle to the ROOT of the hot demos zone (served via its Pull Zone).
# The embed then loads it straight from the demos CDN:
#
#     https://<BUNNY_DEMOS_CDN_HOST>/viewer.js
#
# Run on the server (it sources deploy/.env.prod for the demos-zone creds), or pass them in:
#
#     ./deploy/publish_viewer.sh
#     BUNNY_DEMOS_STORAGE_KEY=... BUNNY_DEMOS_ZONE=demos BUNNY_DEMOS_CDN_HOST=demos.b-cdn.net \
#         ./deploy/publish_viewer.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Convenience: pull the demos-zone creds from deploy/.env.prod if not already in the environment.
ENVF="$ROOT/deploy/.env.prod"
if [[ -f "$ENVF" ]]; then set -a; . "$ENVF"; set +a; fi

HOST="${BUNNY_DEMOS_STORAGE_HOST:-storage.bunnycdn.com}"
ZONE="${BUNNY_DEMOS_ZONE:-demos}"
: "${BUNNY_DEMOS_STORAGE_KEY:?set BUNNY_DEMOS_STORAGE_KEY (write AccessKey for the demos zone)}"
CDN="${BUNNY_DEMOS_CDN_HOST:-<your-demos-pull-zone>}"

# Normalize host vars: strip any scheme + trailing slash so the URLs we build are well-formed
# regardless of how BUNNY_DEMOS_CDN_HOST / _STORAGE_HOST are written in .env.prod.
strip() { local v="$1"; v="${v#http://}"; v="${v#https://}"; echo "${v%/}"; }
HOST="$(strip "$HOST")"
CDN="$(strip "$CDN")"

echo "▶ installing deps + building viewer bundle…"
# Self-contained: clean-install (falls back to `npm install` if there's no lockfile) then build,
# so you only need to run this one script to publish.
( cd "$ROOT/viewer" && { npm ci --silent || npm install --silent; } && npm run build >/dev/null )

put() { # <localfile> <remote-name>
  curl -fsS -X PUT "https://$HOST/$ZONE/$2" \
    -H "AccessKey: $BUNNY_DEMOS_STORAGE_KEY" \
    -H "Content-Type: application/javascript" \
    -H "Cache-Control: public, max-age=300" \
    --data-binary @"$1" >/dev/null
  echo "  → https://$CDN/$2"
}

echo "▶ publishing viewer.js to the demos zone root ('$ZONE')…"
put "$ROOT/viewer/dist/viewer.js" "viewer.js"
put "$ROOT/viewer/dist/viewer.esm.js" "viewer.esm.js"

echo "✓ done. Embed with: <script src=\"https://$CDN/viewer.js\"></script>"
echo "  (Cache-Control is public,max-age=300 so a re-publish rolls forward within ~5 min;"
echo "   purge the demos Pull Zone cache for an instant update.)"
