#!/usr/bin/env bash
# Helper: run auxilium-manus image and forward proxy env to the container
set -euo pipefail

: "${HTTP_PROXY:=}"
: "${HTTPS_PROXY:=}"
: "${NO_PROXY:=}"

CONTAINER_NAME="auxilium-manus"
IMAGE_NAME="auxilium-manus:all-in-one"

echo "Running ${IMAGE_NAME} as ${CONTAINER_NAME} (proxies forwarded)"

docker run -d \
  -e HTTP_PROXY="${HTTP_PROXY}" \
  -e HTTPS_PROXY="${HTTPS_PROXY}" \
  -e NO_PROXY="${NO_PROXY}" \
  -p 3000:3000 -p 8000:8000 \
  --name "${CONTAINER_NAME}" \
  -v auxilium-manus-data:/app/data \
  "${IMAGE_NAME}"

echo "Container started: ${CONTAINER_NAME}"
