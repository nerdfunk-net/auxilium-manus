"""S6-04/S6-07/S6-09/S6-11/S6-12: one network story, hardened containers, no floating tags."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
DOCKER = REPO / "docker"
APP = DOCKER / "docker-compose.yml"

# Every compose file in the repository and the third-party services they run.
COMPOSE_FILES = sorted(
    path
    for path in DOCKER.rglob("*.y*ml")
    if path.name.startswith("docker-compose") and ".prod." not in path.name
)


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _app() -> dict:
    return _load(APP)


def test_postgres_and_redis_are_on_the_internal_data_network_only() -> None:
    document = _app()
    for name in ("manus-postgres", "manus-redis"):
        assert document["services"][name]["networks"] == ["data"]
    assert document["networks"]["data"]["internal"] is True


def test_every_attached_network_is_declared() -> None:
    for path in COMPOSE_FILES:
        document = _load(path)
        declared = set(document.get("networks") or {})
        if ".dev." in path.name:
            # An overlay attaches networks that its base file in the same directory declares.
            base = path.with_name("docker-compose.yml")
            declared |= set(_load(base).get("networks") or {})
        for name, service in document["services"].items():
            networks = service.get("networks") or []
            attached = set(networks if isinstance(networks, list) else networks)
            # The implicit "default" network needs no declaration.
            assert attached - {"default"} <= declared, (
                f"{path.name}:{name} -> {attached - declared}"
            )


def test_only_web_is_on_ingress_and_only_workers_have_egress() -> None:
    services = _app()["services"]
    on_ingress = {n for n, s in services.items() if "ingress" in (s.get("networks") or [])}
    on_egress = {n for n, s in services.items() if "egress" in (s.get("networks") or [])}
    assert on_ingress == {"manus-web"}
    assert on_egress == {"manus-worker", "manus-background-worker"}


def test_published_ports_are_loopback_or_operator_chosen() -> None:
    for path in COMPOSE_FILES:
        for name, service in _load(path)["services"].items():
            for port in service.get("ports", []):
                text = str(port)
                loopback = text.startswith("127.0.0.1:") or text.startswith("${MANUS_WEB_PUBLISH")
                assert loopback, f"{path.name}:{name} publishes {text}"


def test_application_services_are_hardened() -> None:
    for name in ("manus-web", "manus-worker", "manus-background-worker"):
        service = _app()["services"][name]
        assert service["cap_drop"] == ["ALL"], name
        assert "no-new-privileges:true" in service["security_opt"], name
        assert service["pids_limit"] > 0 and service["mem_limit"], name
        # supervisord (root) must be able to signal the programs it dropped to "manus".
        assert {"KILL", "SETUID", "SETGID", "CHOWN"} <= set(service["cap_add"]), name


def test_workers_do_not_inherit_the_web_healthcheck() -> None:
    services = _app()["services"]
    for name in ("manus-worker", "manus-background-worker"):
        assert services[name]["healthcheck"] == {"disable": True}


def test_application_does_not_connect_as_the_postgres_superuser() -> None:
    environment = _app()["x-manus-common-env"]
    assert environment["DATABASE_USERNAME"] == "manus"
    postgres = _app()["services"]["manus-postgres"]["environment"]
    assert postgres["POSTGRES_PASSWORD"] != postgres["APP_DB_PASSWORD"]
    script = (DOCKER / "postgres-init" / "10-app-role.sh").read_text()
    assert "NOSUPERUSER" in script and "ALTER DATABASE manus OWNER TO manus" in script


@pytest.mark.parametrize("path", COMPOSE_FILES, ids=lambda p: str(p.relative_to(DOCKER)))
def test_no_latest_or_untagged_images(path: Path) -> None:
    for name, service in _load(path)["services"].items():
        image = service.get("image")
        if image is None:
            continue  # built locally
        reference = str(image).split("@", 1)[0]
        last = reference.rsplit("/", 1)[-1]
        assert ":" in last, f"{path.name}:{name} has no tag: {image}"
        assert not last.endswith(":latest"), f"{path.name}:{name} uses :latest"
        if "${" in last:
            # A tag taken from the environment must be required, with no moving default.
            assert ":?" in last, f"{path.name}:{name} lets the tag default: {image}"


def test_third_party_services_drop_raw_sockets() -> None:
    for path in COMPOSE_FILES:
        if path == APP:
            continue
        for name, service in _load(path)["services"].items():
            if "image" in service or "build" in service:  # skip override files
                assert "NET_RAW" in service.get("cap_drop", []), f"{path.name}:{name}"


def test_optional_stacks_use_private_networks_not_a_shared_backend() -> None:
    for path in COMPOSE_FILES:
        if path in (APP, DOCKER / "hatchet" / "docker-compose.yml"):
            continue
        declared = _load(path).get("networks") or {}
        assert "backend" not in declared, f"{path.name} still declares the shared backend network"
