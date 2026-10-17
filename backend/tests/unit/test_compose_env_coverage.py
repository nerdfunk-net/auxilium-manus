"""S6-06: every backend setting an operator may need can reach the containers."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
CONFIG = REPO / "backend" / "core" / "config.py"
COMPOSE = REPO / "docker" / "docker-compose.yml"
ENV_EXAMPLE = REPO / "docker" / ".env.example"

# Settings that are deliberately not exposed through compose, with the reason.
INTENTIONALLY_NOT_EXPOSED = frozenset(
    {
        "ALLOW_NETMIKO_ARBITRARY_HOSTS",  # the production guard refuses it
        "BACKEND_SERVER_HOST",  # set by supervisord / the image
        "BACKEND_SERVER_PORT",  # set by supervisord / the image
        "ENABLE_DEV_TOOLS",  # development only, pinned off in the image
        "VAULT_TOKEN",  # static token auth is for development; production uses AppRole
        "VAULT_MANAGE_TOKEN",  # same
        "DATABASE_URL",  # built from DATABASE_* fields
        "MAINTENANCE_DATABASE_URL",  # built from DATABASE_* fields
        "MANUS_REDIS_URL",  # built from MANUS_REDIS_* fields
        "PLUGINS_FILE",  # the image ships the registry
        "INITIAL_PERMISSIONS",  # unused by the backend
        "MANUS_PROCESS_ROLE",  # set per service (web / worker), not shared
        "MANUS_ENV_FILE",  # test hook: a development run only; the image never reads a .env
    }
)

_NAME = re.compile(r"""(?:environ\.get|_get_[a-z]+)\(\s*["']([A-Z][A-Z0-9_]+)["']""")


def _names_read_by_config() -> set[str]:
    return set(_NAME.findall(CONFIG.read_text()))


def test_every_setting_reaches_the_containers_or_is_documented() -> None:
    document = yaml.safe_load(COMPOSE.read_text())
    anchor = {**document["x-manus-common-env"], **document["x-manus-web-only-env"]}
    example = ENV_EXAMPLE.read_text()
    missing = sorted(
        name
        for name in _names_read_by_config()
        if name not in anchor
        and name not in INTENTIONALLY_NOT_EXPOSED
        and not re.search(rf"^#?\s*{name}=", example, re.MULTILINE)
    )
    assert not missing, f"not reachable from docker compose: {missing}"


def test_workers_do_not_receive_web_only_secrets() -> None:
    services = yaml.safe_load(COMPOSE.read_text())["services"]
    web_only = {
        "INITIAL_PASSWORD",
        "INITIAL_USERNAME",
        "VAULT_MANAGE_ROLE_ID",
        "VAULT_MANAGE_SECRET_ID",
        "VAULT_MANAGE_SECRET_ID_FILE",
        "OIDC_REDIRECT_URI_ALLOWLIST",
    }
    for name in ("manus-worker", "manus-background-worker"):
        environment = services[name]["environment"]
        assert not web_only & set(environment), f"{name}: {web_only & set(environment)}"
        assert environment["MANUS_PROCESS_ROLE"] == "worker"
    assert services["manus-web"]["environment"]["MANUS_PROCESS_ROLE"] == "web"
    assert web_only <= set(services["manus-web"]["environment"])
