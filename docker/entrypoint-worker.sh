#!/bin/bash
set -euo pipefail

echo "=== Auxilium Manus Worker Container Startup ==="

mkdir -p /app/data /app/config/certs

if [ "$(id -u)" = "0" ]; then
  # Root-only work: install operator CA certs and fix bind-mount ownership,
  # then drop to the unprivileged 'manus' account for everything else.
  if [ "${INSTALL_CERTIFICATE_FILES:-false}" = "true" ] && ls /app/config/certs/*.crt >/dev/null 2>&1; then
    echo "Installing operator CA certificates from /app/config/certs..."
    cp /app/config/certs/*.crt /usr/local/share/ca-certificates/ && update-ca-certificates
  fi

  chown -R manus:manus /app/data

  exec setpriv --reuid=manus --regid=manus --init-groups "$0" "$@"
fi

echo "Starting ${WORKER_MODULE:-hatchet.worker}..."
exec python -m "${WORKER_MODULE:-hatchet.worker}"
