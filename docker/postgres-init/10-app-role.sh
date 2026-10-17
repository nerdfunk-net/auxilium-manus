#!/bin/sh
# Runs once, on the first initialisation of the data volume (docker-entrypoint-initdb.d).
#
# The application connects as the unprivileged role "manus", which owns only the "manus"
# database; the PostgreSQL superuser ("postgres", POSTGRES_PASSWORD) is never given to the app
# containers. An existing volume keeps whatever role setup it was created with.
set -eu

: "${APP_DB_PASSWORD:?APP_DB_PASSWORD is required}"

psql -v ON_ERROR_STOP=1 -v app_password="$APP_DB_PASSWORD" \
  --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE manus LOGIN PASSWORD :'app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
ALTER DATABASE manus OWNER TO manus;
SQL
