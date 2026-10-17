#!/bin/bash
# Print a Hatchet API token for the application stack (set it as HATCHET_CLIENT_TOKEN in docker/.env).
# Works without the dashboard, so it also works when the dashboard is not published.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
token="$(docker compose run --rm --no-deps -T hatchet-setup-config \
  /hatchet/hatchet-admin token create --config /hatchet/config 2>/dev/null \
  | grep -oE 'eyJ[A-Za-z0-9._-]+' | tail -n 1)"
if [ -z "${token}" ]; then
  echo "Could not create a token. Is the stack up (docker compose ps) and docker/hatchet/.env filled in?" >&2
  exit 1
fi
echo "${token}"
