#!/bin/bash
set -e

echo "=== Auxilium Manus Container Startup ==="
echo "Starting backend and frontend services..."

mkdir -p /app/data/settings
mkdir -p /app/data/git
mkdir -p /app/data/cache
mkdir -p /var/log/supervisor

chown -R root:root /app/data
chmod -R 755 /app/data

SUPERVISORD_CONF="${SUPERVISORD_CONF:-/etc/supervisor/conf.d/supervisord.conf}"

echo "Starting supervisor with ${SUPERVISORD_CONF}..."
exec /usr/bin/supervisord -c "${SUPERVISORD_CONF}"
