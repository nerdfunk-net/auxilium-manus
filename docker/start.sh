#!/bin/bash
set -euo pipefail

echo "=== Auxilium Manus Container Startup ==="

mkdir -p /app/data/settings /app/data/git /app/data/cache /app/data/logs \
         /app/config/certs /var/log/supervisor /run/supervisor

if [ "$(id -u)" = "0" ]; then
  # Root-only work: install operator CA certs and fix bind-mount ownership.
  # (backend/core/cert_installer.py also tries this at Python startup — as
  # 'manus' that is a harmless no-op "Permission denied" log line, since the
  # install already happened here.)
  if [ "${INSTALL_CERTIFICATE_FILES:-false}" = "true" ] && ls /app/config/certs/*.crt >/dev/null 2>&1; then
    echo "Installing operator CA certificates from /app/config/certs..."
    cp /app/config/certs/*.crt /usr/local/share/ca-certificates/ && update-ca-certificates
  fi

  chown -R manus:manus /app/data /var/log/supervisor /run/supervisor
fi

# supervisord stays root: its program configs redirect stdout/stderr to
# /dev/stdout|/dev/stderr, which resolve to PID 1's stdio pipe (owned by root,
# mode 0600). An unprivileged supervisord cannot open it and fails every such
# program with "making dispatchers ... EACCES". Instead supervisord opens the
# log fds as root, then each [program:*] drops to the unprivileged 'manus'
# account via `user=manus` before exec'ing the app (see supervisord*.conf).
SUPERVISORD_CONF="${SUPERVISORD_CONF:-/etc/supervisor/conf.d/supervisord.conf}"

echo "Starting supervisor with ${SUPERVISORD_CONF}..."
exec supervisord -c "${SUPERVISORD_CONF}"
