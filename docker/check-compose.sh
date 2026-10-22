#!/usr/bin/env bash
# Validate every compose file and the overlays that are meant to be combined (docker compose config).
# Needs only the docker CLI with the compose plugin; no containers are started and no image is pulled.
# Used by .github/workflows/docker-ci.yml; also runnable locally: docker/check-compose.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

work="$(mktemp -d)"
placeholders=()
cleanup() {
  rm -rf "${work}"
  if [ "${#placeholders[@]}" -gt 0 ]; then rm -f "${placeholders[@]}"; fi
}
trap cleanup EXIT

# A compose file with `env_file: .env` (no `required: false`) fails `config` when that
# git-ignored file is missing, as it is on a clean checkout and in CI. Create an empty one for the
# run and remove it again; an existing file is left alone.
ensure_env_file() {
  if [ ! -e "$1/.env" ]; then
    : >"$1/.env"
    placeholders+=("$1/.env")
  fi
}

# Dummy values for the variables the compose files refuse to start without. They only have to be
# present; nothing connects with them.
cat >"${work}/app.env" <<'EOF'
SECRET_KEY=ci-secret-key-0000000000000000000000000000
INITIAL_PASSWORD=ci-initial-password-1
CREDENTIAL_ENCRYPTION_KEY=ci-credential-key-000000000000000000000
DATABASE_PASSWORD=ci-database-password-1
POSTGRES_PASSWORD=ci-postgres-password-1
MANUS_REDIS_PASSWORD=ci-redis-password-1
HATCHET_CLIENT_TOKEN=a.b.c
MANUS_AGENT_SECRET=ci-agent-secret-0000000000000000000
EOF
cat >"${work}/hatchet.env" <<'EOF'
HATCHET_DB_PASSWORD=ci-hatchet-db
HATCHET_RABBITMQ_PASSWORD=ci-hatchet-mq
HATCHET_COOKIE_DOMAIN=localhost:8888
HATCHET_ADMIN_EMAIL=ci@example.test
HATCHET_ADMIN_PASSWORD=Aa1-ci-password
EOF
cat >"${work}/optional.env" <<'EOF'
BATFISH_IMAGE_TAG=ci
LITELLM_IMAGE_TAG=ci
LITELLM_DB_PASSWORD=ci-litellm-db
LITELLM_MASTER_KEY=ci-litellm-master
MATTERMOST_IMAGE_TAG=ci
OPENBAO_DEV_ROOT_TOKEN=ci-openbao-token
PYATS_SHIM_TOKEN=ci-pyats-token
EOF

failures=0
check() { # check <env-file> <directory> <compose file>...
  local env_file="$1" dir="$2" args=() file
  shift 2
  for file in "$@"; do args+=(-f "${file}"); done
  if (cd "${dir}" && docker compose --env-file "${env_file}" "${args[@]}" config -q); then
    echo "ok    ${dir}: $*"
  else
    echo "FAIL  ${dir}: $*" >&2
    failures=$((failures + 1))
  fi
}

check "${work}/app.env" . docker-compose.yml
check "${work}/app.env" . docker-compose.yml docker-compose.dev.yml
check "${work}/app.env" . docker-compose.yml docker-compose.agent.example.yml
check "${work}/hatchet.env" hatchet docker-compose.yml
check "${work}/hatchet.env" hatchet docker-compose.yml docker-compose.dev.yml
check "${work}/hatchet.env" hatchet docker-compose.yml docker-compose.prod.yml
check "${work}/optional.env" batfish docker-compose.yaml
check "${work}/optional.env" openbao docker-compose.yaml
ensure_env_file litellm-proxy
check "${work}/optional.env" litellm-proxy docker-compose.yml
check "${work}/optional.env" mattermost docker-compose.yml
check "${work}/optional.env" pyats docker-compose.yml

if [ "${failures}" -ne 0 ]; then
  echo "${failures} compose configuration(s) are invalid" >&2
  exit 1
fi
echo "all compose configurations are valid"
