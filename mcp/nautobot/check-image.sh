#!/usr/bin/env bash
# Build the image and check what the Docker deployment relies on, without a Nautobot:
#   - the container becomes healthy (Nautobot unreachable: the server starts with fallback instructions);
#   - it runs unprivileged on a read-only root filesystem;
#   - /mcp refuses a request without a token (401) and /healthz is open.
# Nothing is pushed. Used by .github/workflows/mcp-ci.yml; also runnable locally:
#   mcp/nautobot/check-image.sh [image-tag]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

image="${1:-nautobot-mcp-ci-check:latest}"
name="nautobot-mcp-ci-check-$$"
trap 'docker rm -f "${name}" >/dev/null 2>&1 || true' EXIT

docker build -t "${image}" .

# Port 1 on localhost: nothing listens there, so the vocabulary load fails fast.
docker run -d --name "${name}" --read-only --cap-drop ALL \
  -e NAUTOBOT_URL=http://127.0.0.1:1 -e NAUTOBOT_TOKEN=ci-token \
  -e MCP_ALLOWED_HOSTS=nautobot-mcp:8000 \
  -e MCP_CLIENT_TOKENS="ci=ci-client-token-0000000000000000000000" \
  "${image}" >/dev/null

health=""
for _ in $(seq 1 40); do
  health="$(docker inspect -f '{{.State.Health.Status}}' "${name}")"
  [ "${health}" = "healthy" ] && break
  sleep 1
done
if [ "${health}" != "healthy" ]; then
  echo "FAIL  container is '${health}', not healthy" >&2
  docker logs "${name}" >&2
  exit 1
fi
echo "ok    container is healthy"

uid="$(docker exec "${name}" id -u)"
if [ "${uid}" = "0" ]; then
  echo "FAIL  the server runs as root" >&2
  exit 1
fi
echo "ok    runs as uid ${uid}"

status="$(docker exec "${name}" python -c "
import urllib.request, urllib.error
req = urllib.request.Request('http://127.0.0.1:8000/mcp', data=b'{}',
                             headers={'Content-Type': 'application/json'})
try:
    print(urllib.request.urlopen(req, timeout=5).status)
except urllib.error.HTTPError as exc:
    print(exc.code)
")"
if [ "${status}" != "401" ]; then
  echo "FAIL  /mcp without a token answered ${status} (expected 401)" >&2
  exit 1
fi
echo "ok    /mcp without a token is refused with 401"

# Config errors must stop the container instead of starting an open server.
if docker run --rm -e NAUTOBOT_URL=http://127.0.0.1:1 -e NAUTOBOT_TOKEN=ci-token \
     -e MCP_ALLOWED_HOSTS=nautobot-mcp:8000 "${image}" >/dev/null 2>&1; then
  echo "FAIL  the server started without any client token" >&2
  exit 1
fi
echo "ok    refuses to start without a client token"
