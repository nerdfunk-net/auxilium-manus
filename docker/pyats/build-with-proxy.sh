#!/usr/bin/env bash
# build-with-proxy.sh - Build the pyATS shim image behind an HTTP(S) proxy.
#
# The pyATS shim image (pyats-shim/Dockerfile) runs `apt-get` and
# `pip install -r requirements.txt` during the build. On a production host that
# only reaches the internet through a proxy, those steps fail unless the proxy
# is passed into the build. This script forwards the proxy settings as Docker
# predefined proxy build args (HTTP_PROXY / HTTPS_PROXY / NO_PROXY, both cases).
#
# Docker treats those names as *predefined* build args: no `ARG` line is needed
# in the Dockerfile, they are excluded from the build cache key, and they are
# NOT baked into the final image or shown in `docker history`. They only affect
# `apt-get` and `pip` while the RUN steps execute.
#
# Usage:
#   # take proxy from the shell environment (http_proxy / HTTPS_PROXY / ...)
#   ./docker/pyats/build-with-proxy.sh
#
#   # or pass explicitly
#   ./docker/pyats/build-with-proxy.sh \
#       --http-proxy  http://proxy.corp:3128 \
#       --https-proxy http://proxy.corp:3128 \
#       --no-proxy    localhost,127.0.0.1,.corp,backend
#
#   # force a clean rebuild (skip layer cache)
#   ./docker/pyats/build-with-proxy.sh --no-cache
#
# After a successful build:
#   cd docker/pyats && docker compose up -d      # no --build; reuse this image
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"

# ---------------------------------------------------------------------------
# Read proxy values: CLI flags override environment; environment accepts the
# conventional upper- and lower-case spellings.
# ---------------------------------------------------------------------------
HTTP_PROXY_VALUE="${HTTP_PROXY:-${http_proxy:-}}"
HTTPS_PROXY_VALUE="${HTTPS_PROXY:-${https_proxy:-}}"
NO_PROXY_VALUE="${NO_PROXY:-${no_proxy:-}}"

NO_CACHE=""
ALLOW_NO_PROXY="false"

while [ $# -gt 0 ]; do
    case "$1" in
        --http-proxy)     HTTP_PROXY_VALUE="$2";  shift 2 ;;
        --https-proxy)    HTTPS_PROXY_VALUE="$2"; shift 2 ;;
        --no-proxy)       NO_PROXY_VALUE="$2";    shift 2 ;;
        --no-cache)       NO_CACHE="--no-cache";  shift ;;
        --allow-no-proxy) ALLOW_NO_PROXY="true";  shift ;;
        -h|--help)
            sed -n '2,33p' "${BASH_SOURCE[0]}"
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

if [ -z "${HTTP_PROXY_VALUE}" ] && [ -z "${HTTPS_PROXY_VALUE}" ]; then
    if [ "${ALLOW_NO_PROXY}" != "true" ]; then
        echo "❌ No proxy configured." >&2
        echo "   Set HTTP_PROXY / HTTPS_PROXY in the environment, or pass" >&2
        echo "   --http-proxy / --https-proxy. Use --allow-no-proxy to build" >&2
        echo "   with direct internet access anyway." >&2
        exit 1
    fi
    echo "⚠️  Building without a proxy (--allow-no-proxy given)."
fi

# ---------------------------------------------------------------------------
# Assemble --build-arg pairs. Pass both upper- and lower-case names so tools
# that only read one spelling (apt reads lower-case, pip reads either) are
# covered.
# ---------------------------------------------------------------------------
BUILD_ARGS=()
add_proxy_arg() {
    # $1 = base name (HTTP_PROXY), $2 = value
    [ -z "$2" ] && return 0
    BUILD_ARGS+=(--build-arg "$1=$2")
    # shellcheck disable=SC2018,SC2019
    BUILD_ARGS+=(--build-arg "$(echo "$1" | tr 'A-Z' 'a-z')=$2")
}
add_proxy_arg "HTTP_PROXY"  "${HTTP_PROXY_VALUE}"
add_proxy_arg "HTTPS_PROXY" "${HTTPS_PROXY_VALUE}"
add_proxy_arg "NO_PROXY"    "${NO_PROXY_VALUE}"

echo "🚀 Building pyATS shim image behind proxy"
echo "=================================================="
echo "   Compose file : ${COMPOSE_FILE}"
[ -n "${HTTP_PROXY_VALUE}" ]  && echo "   HTTP_PROXY   : ${HTTP_PROXY_VALUE}"
[ -n "${HTTPS_PROXY_VALUE}" ] && echo "   HTTPS_PROXY  : ${HTTPS_PROXY_VALUE}"
[ -n "${NO_PROXY_VALUE}" ]    && echo "   NO_PROXY     : ${NO_PROXY_VALUE}"
[ -n "${NO_CACHE}" ]          && echo "   Cache        : disabled (--no-cache)"
echo ""

# ---------------------------------------------------------------------------
# `docker compose` interpolates the whole file (including the runtime-only
# `${PYATS_SHIM_TOKEN:?...}` guard) even for `build`. The token is irrelevant
# to the build, so provide a placeholder when it is not already set. The real
# token is still required later for `docker compose up`.
# ---------------------------------------------------------------------------
export PYATS_SHIM_TOKEN="${PYATS_SHIM_TOKEN:-build-time-placeholder}"

if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
else
    echo "❌ Neither 'docker compose' nor 'docker-compose' is available." >&2
    exit 1
fi

set -x
"${COMPOSE[@]}" -f "${COMPOSE_FILE}" build ${NO_CACHE} "${BUILD_ARGS[@]}"
{ set +x; } 2>/dev/null

echo ""
echo "✅ pyATS shim image built."
echo "   Start it with:  cd \"${SCRIPT_DIR}\" && ${COMPOSE[*]} up -d"
