#!/usr/bin/env python3
"""Create and schema-sync the integration test database.

Usage (from ``backend/``, with the project venv)::

    python scripts/init_test_db.py            # load .env.test, run init_db()
    python scripts/init_test_db.py --drop     # drop manus_test first, then recreate

Behaviour mirrors ``main.py``'s lifespan just enough that the integration
suite's run-trigger / permission paths work:

1. Load ``backend/.env.test`` with ``override=True`` *before* importing
   ``core.config`` so the settings singleton is built from the test values.
2. Rebuild ``core.config.settings`` and rebind the ``core.database`` engine /
   ``SessionLocal`` to the test URL (both modules cache the originals at
   import time).
3. ``--drop``: connect to the maintenance DB and ``DROP DATABASE IF EXISTS``
   the test database.
4. ``core.database.init_db()`` — ``ensure_database_exists()`` + full
   ``AutoSchemaMigration`` from ``Base.metadata``. No migration files.
5. Seed the initial admin user, the RBAC catalog, and the admin role
   assignment.

Guard: refuses to run unless the resolved database name ends in ``_test``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

_ENV_TEST = _BACKEND_ROOT / ".env.test"


def _rebuild_settings_and_engine():
    """Load .env.test, rebuild the settings singleton, rebind the DB engine.

    Returns the freshly built ``Settings`` instance.
    """
    if not _ENV_TEST.exists():
        raise SystemExit(f"Missing {_ENV_TEST} — copy it from the lab notes first.")

    load_dotenv(_ENV_TEST, override=True)

    from core import config as _config

    _config.settings = _config.Settings()

    import core.database as _db

    _db.settings = _config.settings
    _db.engine = create_engine(_config.settings.database_url, pool_pre_ping=True)
    _db.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_db.engine)

    return _config.settings


def _guard_test_database(settings) -> None:
    if not settings.database_name.endswith("_test"):
        raise SystemExit(
            f"Refusing to run: DATABASE_NAME={settings.database_name!r} does not end in '_test'."
        )


def _drop_database(settings) -> None:
    maintenance_url = make_url(settings.maintenance_database_url)
    driver = maintenance_url.drivername.split("+", maxsplit=1)[0]
    admin_engine = create_engine(
        maintenance_url.set(drivername=driver).render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
    )
    try:
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": settings.database_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{settings.database_name}"'))
    finally:
        admin_engine.dispose()
    print(f"Dropped database {settings.database_name!r}")


def _seed_baseline() -> None:
    """Same admin + RBAC bootstrap as main.py's lifespan."""
    import core.database as _db
    from services.auth.auth_service import AuthService
    from services.auth.rbac_seed import seed_rbac
    from services.auth.rbac_service import RBACService

    with _db.SessionLocal() as db:
        admin_user = AuthService(db).ensure_initial_admin()
        seed_rbac(db)
        RBACService(db).assign_role_to_user_by_name(admin_user.id, "admin")
    print("Seeded initial admin user, RBAC catalog, and admin role assignment")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--drop",
        action="store_true",
        help="DROP DATABASE IF EXISTS <name> before recreating it",
    )
    args = parser.parse_args()

    settings = _rebuild_settings_and_engine()
    _guard_test_database(settings)

    if args.drop:
        _drop_database(settings)

    from core.database import init_db

    init_db()
    print(f"Schema synced for {settings.database_url}")

    _seed_baseline()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
