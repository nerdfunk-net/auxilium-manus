"""S6-01/S6-03: nothing publishes the backend, and the defaults bind to loopback."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
DOCKER = REPO / "docker"


def _compose(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _published(service: dict) -> list[str]:
    return [str(p) for p in service.get("ports", [])]


def test_no_service_publishes_the_backend_port() -> None:
    for name, service in _compose(DOCKER / "docker-compose.yml")["services"].items():
        for port in _published(service):
            assert not port.rstrip().endswith(":8000"), f"{name} publishes 8000: {port}"


def test_web_port_is_loopback_by_default() -> None:
    web = _compose(DOCKER / "docker-compose.yml")["services"]["manus-web"]
    (port,) = _published(web)
    assert port.startswith("${MANUS_WEB_PUBLISH:-127.0.0.1:")


def test_backend_binds_loopback_inside_the_container() -> None:
    assert 'BACKEND_HOST="127.0.0.1"' in (DOCKER / "supervisord-web.conf").read_text()
    assert 'BACKEND_HOST="127.0.0.1"' in (DOCKER / "supervisord.conf").read_text()
    assert "BACKEND_HOST=127.0.0.1" in (DOCKER / "Dockerfile.all-in-one").read_text()


def test_hatchet_ports_are_loopback() -> None:
    services = _compose(DOCKER / "hatchet" / "docker-compose.yml")["services"]
    for name, service in services.items():
        for port in _published(service):
            assert port.startswith("127.0.0.1:"), f"{name} publishes {port}"


def test_hatchet_compose_has_no_default_passwords() -> None:
    text = (DOCKER / "hatchet" / "docker-compose.yml").read_text()
    assert "hatchet:hatchet@" not in text
    assert "POSTGRES_PASSWORD: hatchet" not in text
    assert "RABBITMQ_DEFAULT_PASS: hatchet" not in text
    assert "Admin1234" not in text


def test_hatchet_prod_override_publishes_nothing() -> None:
    # `!reset` is a compose-only tag, so check the text rather than parse it.
    text = (DOCKER / "hatchet" / "docker-compose.prod.yml").read_text()
    assert (DOCKER / "hatchet" / ".env.example").exists()
    for service in ("hatchet-engine", "hatchet-dashboard"):
        assert f"{service}:\n    ports: !reset []" in text
    assert 'SERVER_AUTH_COOKIE_INSECURE: "f"' in text
