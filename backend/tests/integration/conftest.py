"""Integration-suite fixtures: env load, DB lifecycle, and seed data.

Ordering constraint (see doc/plans/INTEGRATIONS_TESTS.md §11): ``core/config.py``
calls ``load_dotenv(backend/.env)`` and builds ``settings`` at *import* time. So
this module must load ``.env.test`` and rebuild the settings singleton + the
``core.database`` engine BEFORE any ``core.*`` / ``services.*`` import. Keep the
block below first and import-free above it.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
from urllib.parse import urlparse

import pytest
from dotenv import load_dotenv

_BACKEND = Path(__file__).resolve().parents[2]
_ENV_TEST = _BACKEND / ".env.test"
load_dotenv(_ENV_TEST, override=True)

# --- Rebuild the settings singleton now that .env.test is in os.environ. ------
from core import config as _config  # noqa: E402

_config.settings = _config.Settings()

# --- Re-point the module-level engine / SessionLocal at the test DB. ----------
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

import core.database as _db  # noqa: E402

_db.settings = _config.settings
_db.engine = create_engine(_config.settings.database_url, pool_pre_ping=True)
_db.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_db.engine)

SETTINGS = _config.settings
ENGINE = _db.engine

# Everything below may safely import core.* / services.*.
from tests.integration.helpers import env as env_helpers  # noqa: E402
from tests.integration.helpers.seed import (  # noqa: E402
    seed_git_repository,
    seed_nautobot_source,
    seed_ssh_credential,
)

# Domain tables that go through their own committing sessions (services,
# StepRunner). Truncated by ``clean_tables``; RBAC / users / seeded source rows
# are deliberately excluded.
_TRUNCATE_TABLES = (
    "workflow_step_results",
    "workflow_runs",
    "workflows",
    "inventories",
    "templates",
)


# --------------------------------------------------------------------------- #
# CLI options / markers
# --------------------------------------------------------------------------- #
def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-mutations",
        action="store_true",
        default=False,
        help="Run Phase-2 mutation tests (marked @pytest.mark.mutations).",
    )
    parser.addoption(
        "--drop-test-db",
        action="store_true",
        default=False,
        help="DROP the integration test database before recreating its schema.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "mutations: writes to the shared lab (opt-in, needs --run-mutations)"
    )


def pytest_unconfigure(config: pytest.Config) -> None:
    from tests.integration.helpers.aio import close_loop

    close_loop()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-mutations"):
        return
    skip_mut = pytest.mark.skip(reason="needs --run-mutations")
    for item in items:
        if "mutations" in item.keywords:
            item.add_marker(skip_mut)


# --------------------------------------------------------------------------- #
# Service reachability
# --------------------------------------------------------------------------- #
def _tcp_open(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _http_alive(url: str, timeout: float = 4.0) -> bool:
    import httpx

    try:
        resp = httpx.get(url, timeout=timeout, verify=False, follow_redirects=True)
        return resp.status_code < 500
    except httpx.HTTPError:
        return False


@pytest.fixture(scope="session")
def require_postgres() -> None:
    try:
        with ENGINE.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres unreachable at {SETTINGS.database_url}: {exc}")


@pytest.fixture(scope="session")
def require_nautobot() -> None:
    url = env_helpers.nautobot().url
    if not _http_alive(f"{url.rstrip('/')}/api/"):
        pytest.skip(f"Nautobot unreachable at {url}")


@pytest.fixture(scope="session")
def require_gitea() -> None:
    url = env_helpers.git_repo().url
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not _tcp_open(host, port):
        pytest.skip(f"Gitea unreachable at {host}:{port}")


@pytest.fixture(scope="session")
def require_cisco_device() -> None:
    cisco = env_helpers.cisco()
    if not _tcp_open(cisco.host, 22):
        pytest.skip(f"Cisco device unreachable at {cisco.host}:22")


# --------------------------------------------------------------------------- #
# Database lifecycle
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session", autouse=True)
def _bootstrap_db(request: pytest.FixtureRequest) -> None:
    """Create + schema-sync + seed the test DB once per session.

    Mirrors ``scripts/init_test_db.py``. Guarded on the ``_test`` suffix.
    """
    if not SETTINGS.database_name.endswith("_test"):
        pytest.fail(
            f"DATABASE_NAME={SETTINGS.database_name!r} must end in '_test' for integration tests"
        )

    try:
        with ENGINE.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Postgres unreachable — cannot bootstrap test DB: {exc}")

    drop = request.config.getoption("--drop-test-db") or os.environ.get("MANUS_TEST_DB_DROP") == "1"
    if drop:
        from scripts.init_test_db import _drop_database

        _drop_database(SETTINGS)
        # Re-point the engine at a fresh connection pool after the drop.
        _db.engine.dispose()

    from core.database import init_db
    from services.auth.auth_service import AuthService
    from services.auth.rbac_seed import seed_rbac
    from services.auth.rbac_service import RBACService

    init_db()
    with _db.SessionLocal() as db:
        admin = AuthService(db).ensure_initial_admin()
        seed_rbac(db)
        RBACService(db).assign_role_to_user_by_name(admin.id, "admin")


@pytest.fixture
def db(_bootstrap_db: None) -> Session:
    """Transaction-scoped session — every change rolls back on teardown.

    Use for repository / model round-trips. Anything that commits through its
    own session (services, StepRunner) is invisible here; use ``clean_tables``
    for those.
    """
    connection = ENGINE.connect()
    trans = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        if trans.is_active:
            trans.rollback()
        connection.close()


@pytest.fixture
def clean_tables(_bootstrap_db: None):
    """Truncate the domain tables a test may have committed through a service.

    Runs before *and* after the test. Keeps users / RBAC and the
    session-seeded source rows.
    """

    def _truncate() -> None:
        with ENGINE.begin() as conn:
            conn.execute(
                text(
                    f"TRUNCATE {', '.join(_TRUNCATE_TABLES)} RESTART IDENTITY CASCADE"
                )
            )

    _truncate()
    yield
    _truncate()


# --------------------------------------------------------------------------- #
# Seed fixtures (session-scoped: created once against the real test DB)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def _seed_session(_bootstrap_db: None) -> Session:
    session = _db.SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="session")
def admin_user(_seed_session: Session):
    from repositories.user_repository import UserRepository

    user = UserRepository(_seed_session).get_by_username(SETTINGS.initial_username)
    assert user is not None, "initial admin was not seeded"
    return user


@pytest.fixture(scope="session")
def nautobot_source(_seed_session: Session, require_nautobot: None) -> str:
    cfg = env_helpers.nautobot()
    return seed_nautobot_source(
        _seed_session,
        source_id="itest",
        url=cfg.url,
        token=cfg.token,
        verify_ssl=cfg.verify_ssl,
    )


@pytest.fixture(scope="session")
def git_repository(_seed_session: Session, require_gitea: None) -> dict:
    cfg = env_helpers.git_repo()
    return seed_git_repository(
        _seed_session,
        name="itest",
        url=cfg.url,
        branch=cfg.branch,
        token=cfg.token,
        credential_name="itest-git",
        verify_ssl=cfg.verify_ssl,
    )


@pytest.fixture(scope="session")
def ssh_credential(_seed_session: Session) -> str:
    cisco = env_helpers.cisco()
    return seed_ssh_credential(
        _seed_session,
        name="itest-ssh",
        username=cisco.username,
        password=cisco.password,
    )


@pytest.fixture(scope="session")
def nautobot_credentials():
    import service_factory

    cfg = env_helpers.nautobot()
    return service_factory.credentials_from_connection(
        cfg.url, cfg.token, verify_ssl=cfg.verify_ssl
    )


@pytest.fixture(scope="session")
def nautobot_app(require_nautobot: None):
    """A started ``NautobotService`` registered as the app-wide instance.

    The Nautobot-facing executors / source service read it via
    ``service_factory.get_nautobot_app_service()``.
    """
    import service_factory
    from services.nautobot.client import NautobotService
    from tests.integration.helpers.aio import run as _arun

    svc = NautobotService()
    _arun(svc.startup())
    service_factory.set_nautobot_app_service(svc)
    try:
        yield svc
    finally:
        _arun(svc.shutdown())
