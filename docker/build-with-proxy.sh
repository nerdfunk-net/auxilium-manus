#!/usr/bin/env bash
# Helper: build all-in-one image forwarding proxy env from shell
set -euo pipefail

: "${HTTP_PROXY:=}"
: "${HTTPS_PROXY:=}"
: "${NO_PROXY:=}"

echo "Building auxilium-manus:all-in-one with proxy settings"

docker build \
  --build-arg HTTP_PROXY="${HTTP_PROXY}" \
  --build-arg HTTPS_PROXY="${HTTPS_PROXY}" \
  --build-arg NO_PROXY="${NO_PROXY}" \
  -t auxilium-manus:all-in-one \
  -f docker/Dockerfile.all-in-one .

echo "Build finished: auxilium-manus:all-in-one"
