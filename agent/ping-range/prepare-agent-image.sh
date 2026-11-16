#!/bin/bash
# prepare-agent-image.sh - build the ping agent image and save it for an air-gapped host.
# Run it on a machine with internet access, then transfer the artifact.
set -euo pipefail

cd "$(dirname "$0")"
IMAGE="manus-agent-ping:latest"
ARTIFACT_DIR="airgap-artifacts"
OUTPUT="${ARTIFACT_DIR}/manus-agent-ping.tar"

mkdir -p "${ARTIFACT_DIR}"

# ${arr[@]+...} below: an empty array is "unbound" under set -u in bash < 4.4 (macOS /bin/bash).
proxy_args=()
[ -n "${HTTP_PROXY:-}" ] && proxy_args+=(--build-arg "HTTP_PROXY=${HTTP_PROXY}")
[ -n "${HTTPS_PROXY:-}" ] && proxy_args+=(--build-arg "HTTPS_PROXY=${HTTPS_PROXY}")
[ -n "${NO_PROXY:-}" ] && proxy_args+=(--build-arg "NO_PROXY=${NO_PROXY}")

echo "Building ${IMAGE}"
docker build -t "${IMAGE}" --no-cache ${proxy_args[@]+"${proxy_args[@]}"} .

echo "Saving to ${OUTPUT}.gz"
docker save "${IMAGE}" -o "${OUTPUT}"
gzip -f "${OUTPUT}"

cat <<MSG

Done: ${OUTPUT}.gz ($(du -h "${OUTPUT}.gz" | cut -f1))

On the target host:
  gunzip manus-agent-ping.tar.gz && docker load -i manus-agent-ping.tar
  copy docker-compose.yml and .env.example (as .env) next to each other, set MANUS_AGENT_SECRET
  docker compose up -d      # the image is already loaded; add --no-build if the build context is absent
MSG
