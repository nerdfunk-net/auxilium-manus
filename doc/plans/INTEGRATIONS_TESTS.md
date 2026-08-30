# Integration Tests Plan

Status: implemented (2026-08-30)
Owner: backend
Scope: `backend/tests/integration/`

Implementation notes (deviations from the draft above):
- `RunRepository` has `create_step_result` (singular), not `create_pending_step_results`;
  tests use it directly. `StepRunner.create_pending_step_results` is the plural one.
- Artifact files are flat under `DATA_DIRECTORY/artifacts/<id>.content` (+ `.meta.json`),
  not `artifacts/<run>/…`; `get_for_run(run_uuid, artifact_id)` enforces the run link.
- git-clone / git-pull misconfig (missing/inactive `git_repository_id`) returns a
  `failure` `StepOutcome` (via `run_git_workflow_step`), it does **not** raise. Only
  `get-git-devices` raises `ValueError`. Tests assert accordingly.
- No `pytest-asyncio`/`anyio` plugin in the repo — async executor calls go through
  `tests/integration/helpers/aio.run(coro)` (`asyncio.run`).
- `.env.test` is not dropped/renamed; canonical `DATABASE_*` keys added alongside.
- Phase-2 device / Nautobot mutation tests are scaffolded and `@pytest.mark.skip`
  with their teardown contract documented — only `git-push` is wired end to end.
- `testpaths = ["tests/unit"]` stands, so integration runs must name the path:
  `pytest tests/integration -m "not mutations" --no-cov` (a bare `-m integration`
  collects nothing). See `tests/integration/README.md`.

## 1. Goal

Add an opt-in integration suite that exercises the four external systems the app
integrates with, against **non-production** lab instances:

| System   | Endpoint (from `backend/.env.test`)        | Used by |
|----------|-------------------------------------------|---------|
| Nautobot | `http://localhost:8080`                   | inventory / source service, `get-nautobot-*` steps |
| Git      | `http://127.0.0.1:3030/admin/integration-tests` | `GitService`, `git-*` / `get-git-devices` steps |
| Postgres | `127.0.0.1:5432/manus_test`               | every repository, `init_db()`, run persistence |
| Netmiko  | Cisco IOS device `192.168.178.240` (`noc`/`noc`) | `reachable`, `run-command`, `get-device-configs`, deploy steps |

Four coverage areas requested:

1. Nautobot inventory service (`services/sources/nautobot/*`, `get-nautobot-devices`)
2. Git service (`services/git/*`, `git-clone` / `git-pull` / `git-push` / `get-git-devices`)
3. Database features (init, models, repositories, run/step persistence)
4. Workflow steps that depend on external services — especially Netmiko-based

Confirmed decisions (2026-08-30):

- **DB init**: reuse the app's `core.database.init_db()`. No hand-written DDL. Driven
  by a pytest session fixture, plus a thin `scripts/init_test_db.py` wrapper for
  manual/CI pre-steps.
- **Mutation scope**: read-only tests first (Phase 1). Mutating steps
  (`deploy_config` / `configure_replace` / `upload_config`, `git-push`,
  `add_to_nautobot` / `update_nautobot_device`) are Phase 2, marked slow/opt-in, and
  must clean up after themselves.
- **`.env.test`**: rename DB keys to the canonical names `core/config.py` reads and
  add the loopback flag (see §3.2). File is gitignored (`.gitignore:244`).
- **Runner**: separate `pytest -m integration` invocation with `--no-cov`. Never part
  of the default `pytest` run or the 81% coverage ratchet.

## 2. What already exists

- `backend/tests/integration/README.md` — conventions: mark every test
  `@pytest.mark.integration`, keep secrets/lab IPs out of the tree, plain `pytest`
  only collects `tests/unit`.
- `pyproject.toml` already registers the marker:
  `markers = ["integration: heavy tests against real devices or live services (opt-in)"]`
  and sets `testpaths = ["tests/unit"]`, `addopts = "... --cov-fail-under=81"`.
- `backend/tests/conftest.py` — only puts `backend/` on `sys.path`; loaded for both
  `tests/unit` and `tests/integration`.
- `backend/tests/unit/_git_repo_builder.py` — helpers that build throwaway real git
  repos (`git init`, commits, bare remote). Reuse for git assertions that don't need
  the live Gitea remote.
- `init_db()` (`core/database.py`): `ensure_database_exists()` creates the target DB
  via a maintenance connection, then `AutoSchemaMigration` creates every table,
  column and index from `Base.metadata`. This is exactly what a fresh `manus_test`
  needs — no migration files.
- One-shot run driver: `StepRunner(db).execute_all(run=run, workflow=workflow)` walks
  a workflow's canvas in topological order with a real `DeviceSessionPool`, no
  Hatchet. (Fan-out workflows return a `FanOutSignal` instead of running; keep
  integration workflows linear.)
- `workflow_steps/common/nautobot_source.py::resolve_nautobot_credentials(db,
  source_id, *, step_id)` — the single resolver every Nautobot-facing executor uses
  to turn a `sources.nautobot.<id>` setting (+ linked `credential_id`) into
  `NautobotCredentials`. Covered by `tests/unit/test_nautobot_source_helper.py`.

## 3. Test infrastructure

### 3.1 Directory layout

```
backend/tests/integration/
├── README.md                     # already present
├── conftest.py                   # NEW — env load, DB lifecycle, seed fixtures
├── helpers/
│   ├── __init__.py
│   ├── env.py                    # typed accessors for .env.test values
│   ├── seed.py                   # seed_nautobot_source(), seed_git_repository(), seed_ssh_credential()
│   └── workflows.py              # build_linear_workflow(nodes, edges), make_run()
├── test_db_bootstrap.py          # Area 3 — init_db, schema, health
├── test_repositories_crud.py     # Area 3 — repository round-trips on real Postgres
├── test_run_persistence.py       # Area 3 — WorkflowRun / WorkflowStepResult + artifacts
├── test_nautobot_inventory.py    # Area 1
├── test_git_service.py           # Area 2
├── test_workflow_steps_nautobot.py  # Area 4 — get-nautobot-devices / -attributes
├── test_workflow_steps_git.py       # Area 4 — git-clone / git-pull / get-git-devices
├── test_workflow_steps_netmiko.py   # Area 4 — reachable / run-command / get-device-configs
├── test_workflow_run_end_to_end.py  # cross-cutting — StepRunner.execute_all
└── test_mutations_optin.py          # Phase 2 — device writes, git push, nautobot writes (marked slow)
```

### 3.2 `backend/.env.test` changes (local file, gitignored)

`core/config.py` reads unprefixed `DATABASE_*` (only Redis uses `MANUS_`), and
`core.safe_urls` rejects loopback source URLs unless a flag is set. Update the file to:

```bash
# --- Postgres (canonical names) ---
DATABASE_HOST=127.0.0.1
DATABASE_PORT=5432
DATABASE_NAME=manus_test
DATABASE_MAINTENANCE_NAME=postgres
DATABASE_USERNAME=postgres
DATABASE_PASSWORD=postgres

# --- Runtime ---
ENV=development                    # relaxes production secret guards for the lab
SECRET_KEY=postgres               # already present; fine in development
ALLOW_LOOPBACK_SOURCE_URLS=true   # Nautobot :8080 and Gitea :3030 are on loopback
ALLOW_NETMIKO_ARBITRARY_HOSTS=true  # default in development, set explicit anyway

# --- Redis (optional; only needed to exercise the bulk device cache) ---
# MANUS_REDIS_HOST=127.0.0.1
# MANUS_REDIS_PORT=6379
# MANUS_REDIS_PASSWORD=

# Nautobot / git / cisco blocks: keep as-is
```

The Nautobot/Git/Cisco values in the file are **not** read by `Settings` directly —
they are consumed by the integration helpers (`helpers/env.py`) and turned into DB
rows by seed fixtures.

### 3.3 `scripts/init_test_db.py` (thin wrapper)

```python
"""Create and schema-sync the integration test database.

Usage (from backend/, with the project venv):
    python scripts/init_test_db.py            # load .env.test, run init_db()
    python scripts/init_test_db.py --drop     # drop manus_test first, then recreate
"""
```

Behaviour:

1. `load_dotenv(BACKEND_ROOT / ".env.test", override=True)` **before** importing
   `core.config`.
2. Rebuild the settings singleton (`core.config.settings = core.config.Settings()`)
   in case anything imported it early.
3. `--drop`: connect to the maintenance DB, `DROP DATABASE IF EXISTS manus_test`.
4. Call `core.database.init_db()` (re-create engine bound to the test URL first).
5. Open a session and run `AuthService(db).ensure_initial_admin()`, `seed_rbac(db)`,
   `RBACService(db).assign_role_to_user_by_name(admin.id, "admin")` — mirrors
   `main.py` lifespan so run-trigger / permission paths work.

Guard: refuse to run if `settings.database_name` does not end in `_test`.

CI/local pre-step: `python scripts/init_test_db.py` once before `pytest -m integration`.

### 3.4 `tests/integration/conftest.py`

Key ordering constraint: `core/config.py` calls `load_dotenv(backend/.env)` and builds
`settings` **at import time**. So conftest must load `.env.test` at module top,
before any `core.*` / `services.*` import, then force a settings rebuild.

```python
from __future__ import annotations
import os
from pathlib import Path
import pytest
from dotenv import load_dotenv

_BACKEND = Path(__file__).resolve().parents[2]
load_dotenv(_BACKEND / ".env.test", override=True)

# Rebuild the singleton now that .env.test is in os.environ.
from core import config as _config          # noqa: E402
_config.settings = _config.Settings()

# Re-point the module-level engine/SessionLocal at the test DB.
import core.database as _db                 # noqa: E402
from sqlalchemy import create_engine        # noqa: E402
from sqlalchemy.orm import sessionmaker     # noqa: E402
_db.engine = create_engine(_config.settings.database_url, pool_pre_ping=True)
_db.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_db.engine)
```

Fixtures:

| Fixture | Scope | Purpose |
|---------|-------|---------|
| `_require_services` | session, autouse | Ping Postgres; `httpx` HEAD Nautobot + Gitea; TCP-connect the Cisco device. `pytest.skip("<svc> unreachable")` (not fail) when a system is down so a partial lab still runs a subset. |
| `_bootstrap_db` | session, autouse | Run the same steps as `scripts/init_test_db.py` (drop optional via `--drop-test-db` CLI flag / `MANUS_TEST_DB_DROP=1`). |
| `db` | function | `SessionLocal()`; `try/yield/finally close`. For repository tests wrap in an outer transaction + `SAVEPOINT` and roll back on teardown. |
| `clean_tables` | function | For tests that go through services/`StepRunner` (which commit through their own sessions): `TRUNCATE workflow_step_results, workflow_runs, ... RESTART IDENTITY CASCADE` for the domain tables touched, keeping `users` / RBAC and the session-seeded `settings`, `credentials`, and `git_repositories` rows (the `nautobot_source` / `git_repository` / `ssh_credential` fixtures). |
| `nautobot_source` | session | `seed_nautobot_source(db, source_id="itest", url, token, verify_ssl=False)` → creates the source the same way the API does: a `settings` row `sources.nautobot.itest` holding `{url, verify_ssl}` plus a `credential_id` pointing at a global `Credential` (source `"nautobot"`, type `generic`) that stores the encrypted token. Use `SettingsService(db).create_setting(SettingCreate(key="sources.nautobot.itest", value={"url": …, "verify_ssl": False, "token": …}))` — `create_setting` moves the `token` into the credential and stores the `credential_id`. Returns the source id. This is exactly the shape the fixed executors resolve via `resolve_nautobot_credentials` → `SettingsService.get_source_config_for_step`. |
| `git_repository` | session | `seed_git_repository(db, name="itest", url, branch, auth_type="token", credential_name="itest-git")` → creates a `Credential` (type `generic`/`token`) + a `GitRepository` row via `GitRepositoryService`. Returns the repo id + resolved dict. |
| `ssh_credential` | session | `seed_ssh_credential(db, name="itest-ssh", username="noc", password="noc", visibility="global", type="ssh")` via `CredentialsService`. Returns the credential name. |
| `admin_user` | session | The seeded `admin` user row (for `triggered_by_id`). |

CLI option (in `conftest.py`): `--run-mutations` to enable Phase-2 tests, wired to a
`skip` on `pytest.mark.mutations` otherwise.

### 3.5 Running

```bash
cd backend
source ../.venv/bin/activate
python scripts/init_test_db.py                 # once
python -m pytest -m integration --no-cov       # whole suite
python -m pytest tests/integration/test_git_service.py --no-cov
python -m pytest -m "integration and not mutations" --no-cov   # default lab run
python -m pytest -m "integration and mutations" --no-cov --run-mutations
```

Not added to CI's default gate. Optional: a separate nightly CI job that stands up
the four services and runs `-m "integration and not mutations"`.

## 4. Area 1 — Nautobot inventory service

Targets: `services/sources/nautobot/source_service.py` (`NautobotSourceService`),
`query_service.py`, `evaluator.py`, `metadata_service.py`, built through
`service_factory.build_nautobot_source_service(credentials, db)`.

Setup per test module: construct a real `NautobotService` (`await svc.startup()`),
`service_factory.set_nautobot_app_service(svc)`, build
`NautobotCredentials` from `.env.test` via `service_factory.credentials_from_connection`.
Baseline data: `backend/tests/nautobot-baseline.yaml` — 120 devices (100 network / 20
server), 66 Active / 54 Offline, tags Production 39 / Staging 52 / lab 29, 6 cities.

Tests (all read-only):

1. **`test_connection`** → `NautobotService.test_connection(credentials)` returns a
   `/api/status/` payload (sanity that URL + token + loopback flag line up).
2. **`preview_inventory([])`** returns all 120 devices (`_query_all_devices`).
3. **Filter by status** — build a `LogicalOperation` (`status == "Offline"`); expect
   54. Assert `DeviceInfo` shape (`id`, `name`, `primary_ip4`, `status`, `location`).
4. **Filter by tag** — `tags contains "Production"` → 39; `"Staging"` → 52.
5. **Filter by location** — `location == "City A"` → 21 (matches the baseline header).
6. **AND composition** — `status == "Active" AND tag == "Staging"`; assert the count
   equals the manual intersection over the YAML (compute expected in-test from the
   parsed baseline file so it can't drift).
7. **NOT composition** — all devices `NOT (status == "Offline")` → 66.
8. **`resolve_devices_by_ids`** — take 3 ids from result (2), resolve, expect exactly
   those 3 back.
9. **`search_devices_by_name("lab-01")`** — returns `lab-010..lab-019` + `lab-01`
   style matches, capped at `limit`.
10. **`get_device_details(id)`** — full record has `primary_ip4.address`, interfaces,
    `custom_fields` (`net`, `checkmk_site`, `last_backup`, `snmp_credentials`).
11. **`get_device_attributes(id, ["net","checkmk_site"])`** — returns just the
    requested custom-field bag; cross-check against the YAML entry for that device.
12. **`get_custom_fields()` / `get_field_values("net")`** — includes `netA/netB/lab`.
13. **Cache path (optional, needs Redis)** — `refresh_bulk_device_cache()` returns
    120; a second `preview_inventory` call is served from cache (assert via timing or
    a spy on `_query_all_devices`).
14. **Bad token** → `NautobotAPIError`; **bad host** → `NautobotAPIError`.

Helper: a `baseline` fixture that `yaml.safe_load`s `nautobot-baseline.yaml` and
exposes `devices_by(status=…, tag=…, location=…)` so expected counts are derived,
not hard-coded.

## 5. Area 2 — Git service

Targets: `services/git/service.py` (`GitService` via
`service_factory.build_git_service()`), `repository_service.py`, `auth.py`, `sync.py`,
`device_service.py`, `content_search_service.py`, `version_control_service.py`,
`file_service.py`.

Setup: `git_repository` + `ssh_credential`/token fixtures seed a `GitRepository` row
pointing at `http://127.0.0.1:3030/admin/integration-tests` (branch `main`,
`auth_type="token"`, `verify_ssl=false`). Token from `GIT_TEST_REPO_TOKEN`. Clones go
under a `tmp_path`-based `DATA_DIRECTORY` override so each test starts clean.

Tests:

1. **`GitRepositoryService` CRUD** — create / `get_repository` / `list` / update
   (`branch`) / soft-delete; assert `_to_dict()` shape (the canonical repo dict).
2. **test-connection** — `routers/git` `test_connection` path / `GitService`
   ls-remote against the live Gitea repo succeeds with the token.
3. **clone** — `git_service.clone(repo_dict)` into a fresh dir; `get_repo_path`
   exists, is a valid work tree, `HEAD` on `main`.
4. **open_or_clone idempotency** — second call opens, doesn't re-clone; returns same
   path.
5. **pull** — `clone_or_pull` / `GitService.pull` on an up-to-date tree reports
   `commits_pulled == 0`; no error.
6. **branches / commits / diff** — `GitVersionControlService`: list branches includes
   `main`; list commits returns ≥1 with sha/author/message; diff between `HEAD~1` and
   `HEAD` (skip if the repo has a single commit).
7. **file browsing** — `GitFileService`: list a commit's files (respects
   `ALLOWED_FILE_EXTENSIONS`), read one file's content + history.
8. **device discovery** — `GitDeviceService.fetch_devices(repo_dict, pattern,
   directory)` against a known devices YAML in the repo; assert parsed
   `DeviceContext`-shaped dicts (`name`, `primary_ip4.address`, `platform`).
   Pre-req: put a small `devices/*.yaml` in the Gitea repo (documented in the test
   module docstring; if absent, `xfail` with a clear message).
9. **content search** — `GitContentSearchService` finds a known string, returns
   file + line hits.
10. **auth negative** — wrong token → auth error surfaced as a `GitResult(success=
    False)` / typed exception, not a raw stack trace.
11. **offline fallback** — `_git_repo_builder.make_repo_with_remote(tmp_path)` for a
    fully local clone/commit/push cycle that needs no Gitea (keeps a smoke test green
    when the remote is down).

## 6. Area 3 — Database features

Targets: `core/database.py` (`init_db`, `ensure_database_exists`, `ping_database`),
`migrations/auto_schema.py`, `core/models/*`, `repositories/*`,
`repositories/base.py`, `RunRepository`, `services/execution/run_service.py`,
`FilesystemArtifactService`.

Tests:

1. **`init_db()` on an empty DB** — after `--drop-test-db`, `init_db()` creates all
   14 tables. Assert via SQLAlchemy `inspect(engine).get_table_names()` ⊇ the
   `Base.metadata.tables` keys.
2. **Idempotent re-run** — second `init_db()` reports zero structural changes
   (`AutoSchemaMigration.run()` result: `tables_created == columns_added ==
   indexes_created == 0`).
3. **Schema drift detector** — `scripts/database/sync.py` logic
   (`AutoSchemaMigration.analyze()`): `diff.has_differences is False` against a
   freshly synced DB. This is a real regression guard for model/DB skew.
4. **`ping_database()`** — succeeds; with a bogus URL raises.
5. **Indexes present** — spot-check a couple declared indexes exist
   (`workflows.name`, `credentials.owner_user_id`, the `workflow_step_results` FK
   index).
6. **Repository round-trips on real Postgres** (things in-memory SQLite can't prove):
   - `CredentialsService` create → `password_encrypted` is bytes, `get_decrypted_
     password` round-trips; `visibility`/`owner_user_id` defaults; server-default
     `created_at` populated by Postgres.
   - `SettingsRepository` create/get/update/delete with a `JSON` value column
     (dict in / dict out, nested).
   - `GitRepositoryService` unique-name constraint raises on duplicate.
   - `WorkflowRepository` create with `canvas_nodes`/`canvas_edges` JSON, reload,
     structural equality.
   - `InventoryRepository` create filter + static inventories, `get_by_name`
     active-only filter.
   - RBAC: `seed_rbac` is idempotent; `RBACService.has_permission` precedence
     (user override > role grant > default deny) against real Postgres.
7. **Run + step persistence** (`RunRepository`):
   - `create_pending_step_results` writes one `pending` row per node.
   - `update_step_result(status=…)` transitions; `update_run_status` with
     `finished_at`.
   - `WorkflowStepResult` ↔ `WorkflowRun` FK + cascade on run delete.
   - Metadata vs content split: metadata (status/timestamps/device ids) lives on the
     row; content (command output) goes through `FilesystemArtifactService.store` and
     comes back via `RunService.get_run_artifact` — assert the artifact file lands
     under `DATA_DIRECTORY/artifacts/<run>/…` and the row only holds the ref.
8. **`RunService.trigger_run`** (no Hatchet dispatch assertion) — creates a
   `WorkflowRun` in `pending`/`queued` with correct `trigger_type`,
   `triggered_by_id`, `device_ids`; `list_runs` / `get_run` / `delete_run` happy
   paths and the access check (`_assert_workflow_access`).
9. **Retention** — `RetentionService` / `purge_retention` on seeded old runs deletes
   rows + orphan artifact dirs (use a small `RUN_RETENTION_DAYS`).

DB reset: transaction-rollback `db` fixture for 6; `clean_tables` truncation for 7–9.

## 7. Area 4 — Workflow steps depending on external services

Each executor has the signature
`execute(*, config, context, run, artifact_service, node_id, device_sessions)` and is
dispatched via `services/execution/step_registry.py::STEP_REGISTRY`. Two ways to test:

- **Direct executor call** — build a `WorkflowContext`, a persisted `WorkflowRun`
  (needs an `object_session`, so add it to `db` and pass that `run`), a real
  `FilesystemArtifactService(tmp_data_dir)`, and a real
  `DeviceSessionPool(max_workers=2, enabled=True)`. Call `execute(...)`, assert the
  returned `list[StepOutcome]` and the new `context`.
- **Through `StepRunner`** — see §8.

### 7.1 Netmiko-based steps (Cisco IOS `192.168.178.240`, `noc`/`noc`)

Device context per test: `DeviceContext(id="d1", name="lab-cisco",
hostname="192.168.178.240", primary_ip4="192.168.178.240/24",
network_driver="cisco_ios", platform="cisco_ios")`.

1. **`reachable`** — `config={"ping_count":2,"required_replies":1,
   "timeout_seconds":2}`; expect a `success` outcome containing the device,
   `parsed["<node>.reachability"].reachable is True`, `DeviceStatus.OK`.
   Negative: a `DeviceContext` with an unused RFC5737 IP → `failure` outcome,
   `code="unreachable"`.
2. **`run-command` (read-only)** — `config={"credential_reference":"itest-ssh",
   "commands":["show version","show ip interface brief"]}`. Expect `success`;
   `device.command_results["<node>"]` has 2 `CommandResult`s with `output_ref`s;
   fetch each ref via `artifact_service` and assert non-empty text containing
   `Cisco`. Verify base-state invariant indirectly: a second `run-command` node in
   the same pool reuses one SSH session (assert `len(pool._sessions) == 1`).
3. **`run-command` + TextFSM** — `use_textfsm=True` on `show ip interface brief`;
   `output_ref` content parses as a JSON list; summary reads `"N row(s) parsed"`.
4. **`run-command` genie (optional)** — only if a pyATS shim source is seeded;
   otherwise assert the executor's documented non-fatal skip (device stays `OK`,
   no `parsed` genie key) when `pyats_source_id` points nowhere.
5. **`get-device-configs`** — `config_format="running"` then `"both"`. Expect
   `success`; `running_config_ref` (and `startup_config_ref` for `both`) resolve to
   text starting with `!` / containing `hostname`; `Capability.RUNNING_CONFIG` set.
6. **Credential negative** — `credential_reference="does-not-exist"` →
   `CredentialReferenceNotFoundError` (`ValueError` subclass) out of
   `resolve_ssh_credential`; wrong password credential → device `failure` with an
   auth `code`, not an exception.
7. **`parse_cisco_config`** — feed a `running_config_ref` from test 5 into the
   `parse-cisco-config` step; assert structured output (hostname, interfaces).
   Bridges Netmiko output → a pure step.

### 7.2 Nautobot-based steps

All five Nautobot-facing executors (`get-nautobot-devices`, `get-nautobot-attributes`,
`get-ise-devices`, `add-to-nautobot`, `update-nautobot-device`) resolve their source
through `workflow_steps/common/nautobot_source.py::resolve_nautobot_credentials`
(→ `SettingsService.get_source_config_for_step` → `credential_id` → decrypted token).
The `nautobot_source` fixture seeds the source in that same `credential_id`-backed
shape, so these tests double as end-to-end coverage of that resolution path.

8. **`get-nautobot-devices` (filter)** — seed `sources.nautobot.itest`; `config=
   {"nautobot_source_id":"itest","inventory_type":"filter","device_filter":
   {<FilterTree: status == Offline>}}`. Expect `success`, `len(context.devices) ==
   54`, each `DeviceContext` carries `source_id="itest"`, and
   `context.metadata["<node>.total"] == 54`.
9. **`get-nautobot-devices` (static)** — `inventory_type="static"`,
   `device_ids=[<3 real ids>]` → exactly those 3.
10. **`get-nautobot-attributes`** — after step 9, resolve `["net","checkmk_site"]`
    for the devices; assert the attribute bag matches the baseline YAML.
11. **Misconfig** — empty `nautobot_source_id` → `ValueError` ("not configured");
    unknown source id → `ValueError` ("not found in settings"); a source row whose
    `credential_id` points at a deleted credential → `ValueError` ("credential is
    missing"). All three come from `resolve_nautobot_credentials`.

### 7.3 Git-based steps

12. **`git-clone`** — `config={"git_repository_id": <seeded id>}`; outcome dict has
    `operation="clone"`, `path` exists on disk, `branch="main"`.
13. **`git-pull`** — after 12, `git-pull` returns success, `commits_pulled == 0`.
14. **`get-git-devices`** — `config={"git_repository_id":<id>,
    "filename_pattern":"*.yaml","directory":"devices"}`; expect ≥1 `DeviceContext`
    in the resulting context and `metadata["<node>.files_read"] >= 1`. (Same repo
    pre-req as §5.8.)
15. **Misconfig** — missing `git_repository_id` → `ValueError`; inactive repo row →
    `ValueError` from `load_git_repository`.

## 8. Cross-cutting — full workflow run via `StepRunner`

`test_workflow_run_end_to_end.py`. Uses `helpers/workflows.build_linear_workflow()`
to persist a `Workflow` row with `canvas_nodes` / `canvas_edges`, `make_run()` to
persist a `WorkflowRun` (`run_mode="normal"`, `trigger_type="manual"`,
`triggered_by_id=admin.id`), then:

```python
runner = StepRunner(db)
try:
    ok = await runner.execute_all(run=run, workflow=wf)
finally:
    await runner.close_device_sessions()
```

Scenarios (linear, no fan-out):

1. **Nautobot → reachable** — `get-nautobot-devices` (filter: a small location,
   e.g. `City C` = 16) → `reachable`. Assert `execute_all` returns a bool,
   `WorkflowStepResult` rows are `success`/`failed` (not `pending`), run status
   persisted, per-device reachability recorded. The lab device likely isn't in
   Nautobot's range, so assert the *mechanics* (steps ran, statuses written), not
   universal reachability.
2. **Static device → run-command → get-device-configs → store-artifact** — a
   `get-from-list`/static inventory node seeded with the real Cisco IP, then two
   Netmiko steps sharing one pooled SSH session, then `store-artifact` persisting
   the running config. Assert: one artifact file on disk, `WorkflowStepResult`
   content refs, run `success`, `pool` reused the session across the two Netmiko
   steps.
3. **Git → get-git-devices → reachable** — end-to-end from the live Gitea repo.
4. **Failure propagation** — point `run-command` at a bad credential; assert the
   downstream `get-device-configs` node is `skipped` and `execute_all` returns
   `False`.

These give one honest "the whole chain works against real systems" signal per area.

## 9. Phase 2 — mutation tests (opt-in, `@pytest.mark.mutations`, `--run-mutations`)

Each test must restore prior state in a `finally` / fixture teardown.

- **`deploy_config` / `configure_replace_config`** — push a no-op-ish change
  (e.g. `snmp-server contact itest-<uuid>` then remove it; or a loopback
  interface created then `no interface`). Assert `DeployResult.success`,
  `write_config` saved, and the running config reflects then un-reflects the change.
- **`upload_config`** — SCP a small file to `flash:` / `bootflash:`, verify via
  `dir`, then delete it.
- **`git-push`** — `git-clone` → write a file under `itest/<uuid>/` → `git-push` to
  a scratch branch `itest/<run-uuid>`; assert the commit is on the remote; teardown
  deletes the remote branch.
- **`add_to_nautobot` / `update_nautobot_device`** — create a device
  `itest-<uuid>` in a lab location, assert it resolves via the source service,
  update a custom field, then delete it. Never touch `lab-0xx` baseline devices.

## 10. Task list

1. **Infra**
   - [x] Update `backend/.env.test` per §3.2.
   - [x] `backend/scripts/init_test_db.py` (+ `_test` name guard).
   - [x] `backend/tests/integration/conftest.py` — env load + settings/engine rebuild,
     `require_*` skip fixtures, `_bootstrap_db`, `db`, `clean_tables`, seed fixtures,
     `--run-mutations` / `--drop-test-db` options.
   - [x] `backend/tests/integration/helpers/{env,seed,workflows,aio}.py`.
2. [x] **Area 3 — DB** (`test_db_bootstrap.py`, `test_repositories_crud.py`,
   `test_run_persistence.py`).
3. [x] **Area 1 — Nautobot inventory** (`test_nautobot_inventory.py` + `baseline`
   fixture/parser).
4. [x] **Area 2 — Git** (`test_git_service.py`). Still TODO: add a small
   `devices/*.yaml` to the Gitea repo (device-discovery tests `xfail` until then).
5. [x] **Area 4 — steps** (`test_workflow_steps_{netmiko,nautobot,git}.py`).
6. [x] **Cross-cutting** (`test_workflow_run_end_to_end.py`).
7. [~] **Phase 2** (`test_mutations_optin.py`) — `git-push` done; device/Nautobot
   writes scaffolded + skipped.
8. [x] **Docs** — `tests/integration/README.md` rewritten; `CLAUDE.md` note added.
9. [ ] **Optional** — nightly CI job (`-m "integration and not mutations"`).

## 11. Risks & open items

- **Nautobot token storage (fixed 2026-08-30, pre-plan).** The five Nautobot-facing
  executors used to read `setting.value["token"]` inline via
  `SettingsRepository.get_by_key`, which is always empty now that
  `SettingsService.create_setting` stores the token as a `Credential` +
  `credential_id`. They were migrated to
  `workflow_steps/common/nautobot_source.py::resolve_nautobot_credentials`
  (→ `SettingsService.get_source_config_for_step`), matching the ISE / pyATS /
  Mattermost source-config pattern. The `nautobot_source` fixture seeds the
  `credential_id`-backed shape, and §7.2 tests 8–11 exercise the resolver end to end.
  No integration test should special-case an inline `token` — that path no longer
  exists.
- **Loopback URLs.** Nautobot `:8080` and Gitea `:3030` resolve to loopback;
  `ALLOW_LOOPBACK_SOURCE_URLS=true` in `.env.test` is mandatory or every Nautobot/git
  call raises `UnsafeURLError`.
- **`settings` singleton import order.** Anything that imports `core.config` before
  `conftest.py` runs its `load_dotenv` locks in `backend/.env` values. Mitigated by
  doing the dotenv load + `Settings()` rebuild + engine rebind at the very top of
  `tests/integration/conftest.py`; keep that block first and import-free above it.
- **Shared lab mutstate.** Baseline Nautobot devices and the Gitea `main` branch must
  stay pristine — Phase 2 tests only ever create uniquely-named (`itest-<uuid>`)
  objects and scratch branches, with teardown.
- **Device session teardown.** Every test that builds a `DeviceSessionPool` or
  `StepRunner` must `await pool.close()` / `await runner.close_device_sessions()` in
  `finally` or the thread executor leaks across tests.
- **Redis optional.** The bulk device cache path is skipped unless
  `MANUS_REDIS_*` is set and reachable; core inventory tests must pass with
  `cache_service=None`.
- **Hatchet not involved.** Integration tests drive `StepRunner.execute_all`
  directly. Hatchet orchestration (fan-out, durable waits, debug stepping) stays
  covered by `tests/unit`.
- **Parallelism.** Run the integration suite single-process (no `-n auto`) — shared
  lab device + shared `manus_test` schema.
