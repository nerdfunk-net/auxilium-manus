# Integration tests

Heavy tests against real network devices and/or live external services
(Nautobot, Gitea, Postgres, a Cisco IOS device).

**Not run by default.** Plain `pytest` from `backend/` only collects `tests/unit`
and never touches the 81% coverage ratchet.

## What it covers

| Area | Modules | Targets |
|------|---------|---------|
| 1 — Nautobot inventory | `test_nautobot_inventory.py` | `services/sources/nautobot/*`, `get-nautobot-*` |
| 2 — Git service | `test_git_service.py` | `services/git/*` |
| 3 — Database | `test_db_bootstrap.py`, `test_repositories_crud.py`, `test_run_persistence.py` | `core/database.py`, `migrations/auto_schema.py`, repositories, run persistence |
| 4 — Workflow steps | `test_workflow_steps_{netmiko,nautobot,git}.py` | executors that depend on external services |
| cross-cutting | `test_workflow_run_end_to_end.py` | `StepRunner.execute_all` |
| Phase 2 (opt-in) | `test_mutations_optin.py` | device writes, `git-push`, Nautobot writes |

## Setup

1. Copy / edit `backend/.env.test` (gitignored). Required keys:

   | Key | Purpose |
   |-----|---------|
   | `DATABASE_HOST` / `DATABASE_PORT` / `DATABASE_NAME` (`*_test`) / `DATABASE_USERNAME` / `DATABASE_PASSWORD` | test Postgres — canonical names `core/config.py` reads |
   | `DATABASE_MAINTENANCE_NAME` | DB used to `CREATE` / `DROP` the test DB (`postgres`) |
   | `ENV=development` | relaxes production secret guards for the lab |
   | `SECRET_KEY` | JWT signing (any value while `ENV=development`) |
   | `ALLOW_LOOPBACK_SOURCE_URLS=true` | **mandatory** — Nautobot `:8080` / Gitea `:3030` are loopback |
   | `ALLOW_NETMIKO_ARBITRARY_HOSTS=true` | allow SSH to the lab device |
   | `NAUTOBOT_HOST` / `NAUTOBOT_TOKEN` / `NAUTOBOT_VERIFY_SSL` | Nautobot lab instance (seeded with `tests/nautobot-baseline.yaml`) |
   | `GIT_TEST_REPO_URL` / `GIT_TEST_REPO_TOKEN` / `GIT_TEST_REPO_BRANCH` / `GIT_TEST_REPO_VERIFY_SSL` | Gitea lab repo |
   | `CISCO_DEVICE` / `CISCO_DEVICE_USERNAME` / `CISCO_DEVICE_PASSWORD` | Cisco IOS lab device |
   | `MANUS_REDIS_HOST` (optional) | enables the bulk-device-cache test |

2. Create + schema-sync the test database once:

   ```bash
   cd backend
   source ../.venv/bin/activate
   python scripts/init_test_db.py            # load .env.test, run init_db(), seed admin + RBAC
   python scripts/init_test_db.py --drop     # drop manus_test first, then recreate
   ```

   The session `_bootstrap_db` fixture also does this automatically the first
   time you run the suite (add `--drop-test-db` or `MANUS_TEST_DB_DROP=1` to
   force a drop). The `_test` suffix guard refuses anything else.

## Run

```bash
cd backend
source ../.venv/bin/activate

# `testpaths = ["tests/unit"]` in pyproject.toml, so always name the path:
python -m pytest tests/integration --no-cov                          # whole suite
python -m pytest tests/integration/test_git_service.py --no-cov
python -m pytest tests/integration -m "not mutations" --no-cov       # default lab run
python -m pytest tests/integration -m mutations --no-cov --run-mutations
```

Always name `tests/integration` (marker filters alone won't collect it), always
`--no-cov` (integration runs must never move the unit ratchet), and
single-process — no `-n auto`: the suite shares one lab device and one
`manus_test` schema.

## Markers & flags

| Marker / flag | Meaning |
|---------------|---------|
| `@pytest.mark.integration` | every test / module here |
| `@pytest.mark.mutations` | writes to the shared lab; skipped unless `--run-mutations` |
| `--run-mutations` | enable Phase-2 mutation tests |
| `--drop-test-db` / `MANUS_TEST_DB_DROP=1` | drop `manus_test` before the schema sync |

## Conventions

- A system that is down → `pytest.skip` (the `require_*` fixtures), never a hard
  fail, so a partial lab still runs a subset.
- Keep integration workflows **linear** — fan-out returns a `FanOutSignal`
  instead of running.
- Every test that builds a `DeviceSessionPool` / `StepRunner` must
  `await pool.close()` / `runner.close_device_sessions()` in `finally`.
- Phase-2 tests only ever create uniquely-named (`itest-<uuid>`) objects and
  scratch branches, and undo them in teardown. The Nautobot baseline and the
  Gitea `main` branch stay pristine.
- Credentials and lab IPs live only in `backend/.env.test` (gitignored) — never
  commit them.
