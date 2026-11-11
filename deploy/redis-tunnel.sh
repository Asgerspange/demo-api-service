#!/usr/bin/env bash
# Forward the server's Redis to localhost so dev can use it.
#
# The server's redis_cache container is bound to 127.0.0.1:6379 (no auth, not publicly
# reachable), shared with isdigital/csstrats. demoviewer talks to it over this tunnel and
# stays on logical db 3 (REDIS_URL=redis://127.0.0.1:6379/3). Local 6379 is free because
# the dev stack no longer runs its own Redis.
#
# Usage:
#   ./deploy/redis-tunnel.sh <user>@<server>        # e.g. ./deploy/redis-tunnel.sh deploy@isdigital.dk
#   SSH_HOST=deploy@host ./deploy/redis-tunnel.sh    # or via env
#
# Leave it running in a terminal (or add `-f` to background it). Verify with:
#   redis-cli -p 6379 -n 3 ping   →  PONG
set -euo pipefail

HOST="${1:-${SSH_HOST:-}}"
if [[ -z "$HOST" ]]; then
  echo "usage: $0 <user>@<server>   (or set SSH_HOST)" >&2
  exit 1
fi

LOCAL_PORT="${LOCAL_REDIS_PORT:-6379}"
REMOTE="${REMOTE_REDIS:-127.0.0.1:6379}"

echo "Tunneling localhost:${LOCAL_PORT} -> ${REMOTE} via ${HOST} (Ctrl-C to stop)"
exec ssh -N -L "${LOCAL_PORT}:${REMOTE}" "${HOST}"
