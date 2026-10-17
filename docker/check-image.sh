#!/usr/bin/env bash
# Build the application image and check what the Docker deployment relies on:
#   - Node.js is v26 (the same binary the frontend was built with) and there is no distro npm;
#   - `next start` serves /login with HTTP 200 as the unprivileged `manus` user.
# Nothing is pushed. Used by .github/workflows/docker-ci.yml; also runnable locally:
#   docker/check-image.sh [image-tag]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

image="${1:-manus-ci-check:latest}"
docker build -f docker/Dockerfile.all-in-one -t "${image}" .

version="$(docker run --rm --entrypoint "" "${image}" node --version)"
case "${version}" in
  v26.*) echo "ok    node ${version}" ;;
  *) echo "FAIL  expected Node v26, the image has ${version}" >&2; exit 1 ;;
esac

if docker run --rm --entrypoint "" "${image}" sh -c 'command -v npm >/dev/null'; then
  echo "FAIL  the image contains npm (it should only carry the node binary)" >&2
  exit 1
fi
echo "ok    no npm in the image"

status="$(docker run --rm --entrypoint "" -u manus "${image}" sh -c '
  cd /app/frontend
  node node_modules/next/dist/bin/next start -p 3000 >/tmp/next.log 2>&1 &
  for _ in $(seq 1 30); do
    code="$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3000/login || true)"
    [ "${code}" = "200" ] && break
    sleep 1
  done
  echo "${code}"
')"
if [ "${status}" != "200" ]; then
  echo "FAIL  next start answered ${status:-nothing} for /login (expected 200)" >&2
  exit 1
fi
echo "ok    next start serves /login with 200"
