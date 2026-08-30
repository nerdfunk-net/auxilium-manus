# Backend tests

```text
backend/tests/
  conftest.py            # puts backend/ on sys.path (loaded for unit + integration)
  nautobot-baseline.yaml # 120-device fixture the lab Nautobot is seeded from
  unit/                  # mocked / in-memory — the default suite (~1950 tests)
  integration/           # real devices / live services — opt-in (68 tests)
```

Unit tests use stdlib `unittest` (`TestCase` / `IsolatedAsyncioTestCase`) and run
under **pytest**. External I/O is mocked; DB-backed cases use in-memory SQLite.
**No running PostgreSQL, Redis, Hatchet, or Nautobot is required for `unit/`.**

Integration tests talk to real lab systems and are never collected by a plain
`pytest` run — see [`integration/README.md`](integration/README.md).

---

## 1. Prerequisites

1. Project virtualenv at the **repo root** (`.venv/`, Python 3.14 — *not*
   `backend/.venv`).
2. Dev dependencies installed once:

   ```bash
   # from repo root
   source .venv/bin/activate
   pip install -r backend/requirements-dev.txt
   ```

Pytest config lives in `backend/pyproject.toml`: `testpaths = ["tests/unit"]`,
`addopts = "-q --cov --cov-report=term-missing --cov-fail-under=81"`.

---

## 2. Running the unit suite (default)

From **`backend/`**:

```bash
cd backend
python -m pytest                       # whole unit suite + coverage gate
python -m pytest --no-cov              # skip the 81% whole-suite gate (faster, for subsets)
```

From the **repo root**: `python -m pytest backend/tests/unit`

| Goal | Command |
|------|---------|
| One file | `python -m pytest tests/unit/test_rbac_service.py` |
| One class | `… test_rbac_service.py::RBACServiceHasPermissionTests` |
| One test | `… ::RBACServiceHasPermissionTests::test_role_grant_allows` |
| By keyword | `python -m pytest -k "rbac or fan_out"` |
| Per-test list + status column | `python -m pytest -o addopts= --no-cov -v` |
| End-of-run status summary | `python -m pytest --no-cov -rA` (`-ra` = all but passes, `-rfE` = only failures) |
| Coverage for one module | `python -m pytest --cov=services/git --cov-report=term-missing tests/unit -k git` |
| stdlib runner | `python -m unittest discover -s tests/unit` |

> The project's `addopts` includes `-q`, so the default output is progress
> characters (`.` pass, `F` fail, `x` xfail, `s` skip). `-o addopts=` clears it so
> `-v` can show the classic one-line-per-test view.

**`xfailed`** = a test marked/known to fail did fail (expected — not a failure).
**`deselected`** = filtered out by a `-m` / `-k` expression.

---

## 3. Running the integration suite (opt-in)

Needs `backend/.env.test` (gitignored) and a one-time DB bootstrap. Full details
in [`integration/README.md`](integration/README.md).

```bash
cd backend
source ../.venv/bin/activate
python scripts/init_test_db.py                             # once: create + seed manus_test

# `testpaths = ["tests/unit"]`, so always name the path:
python -m pytest tests/integration -m "not mutations" --no-cov          # default lab run
python -m pytest tests/integration/test_git_service.py --no-cov -rA
python -m pytest tests/integration -m mutations --no-cov --run-mutations # Phase-2 writes
```

Always `--no-cov` (integration runs must never move the unit ratchet) and
single-process (no `-n auto`) — one shared lab device, one `manus_test` schema.
A system that is down → the test **skips** (not fails).

---

## 4. What is implemented

### 4.1 Unit tests (`tests/unit/`, ~1950 tests, ~185 files)

| Area | Representative files | Covers |
|------|----------------------|--------|
| **Workflow engine** | `test_step_runner_*`, `test_execution_graph`, `test_effective_produces`, `test_workflow_context_*`, `test_canvas_decoration_execution_plan`, `test_debug_mode_stepping`, `test_fan_in`, `test_fan_out_metadata`, `test_step_result_status` | topological walk, blocked-by-failure propagation, funnels, fan-out signalling, capability guards (`requires`/`produces`), context merge/serialize, debug stepping |
| **Workflow steps** (one file per executor) | `test_reachable_executor`, `test_run_command_executor`, `test_get_device_configs_executor`, `test_get_from_list_executor`, `test_get_nautobot_attributes_executor`, `test_deploy_rendered_template_executor`, `test_render_jinja_template_executor`, `test_store_artifact_executor`, `test_compare_data_executor`, `test_parse_cisco_config_executor`, `test_route_on_*_executor`, `test_update_attribute_executor`, `test_git_workflow_steps`, `test_notify_*_executor`, … | per-step config parsing, success/failure outcomes, device enrichment, error codes (`ValueError` = config, `RuntimeError` = execution) |
| **Git** (24 files) | `test_git_service_engine`, `test_git_repository_service*`, `test_git_auth_credentials`, `test_git_sync`, `test_git_version_control_service`, `test_git_file_service`, `test_git_device_service`, `test_git_content_search_service`, `test_git_paths`, `test_git_push_helpers`, `test_git_*_router*` | clone/pull/push/commit/fetch against `file://` repos, `GitRepository` CRUD, credential resolution, path sandboxing, browsing/diff/search, router auth |
| **Nautobot & sources** (24 files) | `test_nautobot_client`, `test_sources_nautobot_*` (query / evaluator / metadata / persistence / export / source service), `test_nautobot_resolvers`, `test_nautobot_managers`, `test_nautobot_devices_*`, `test_nautobot_source_helper`, `test_sources_crud_routers`, `test_source_connection_tests` | GraphQL/REST client, logical-filter evaluation, resolver + manager layers, device create/update workflows, `sources.*` settings CRUD |
| **ISE / pyATS / Mattermost** | `test_ise_*` (6), `test_pyats_*` (5), `test_mattermost_*` (3) | external-client wrappers, source-config services, their executors and router auth |
| **Netmiko / device I/O** | `test_netmiko_*` (6), `test_device_session_pool`, `test_parse_cisco_config_executor` | connection handling, running-config fetch, deploy, file upload, platform resolution, pooled-session reuse |
| **Auth & RBAC** | `test_rbac_service`, `test_rbac_seed`, `test_rbac_elevation`, `test_rbac_roles_router`, `test_router_auth`, `test_require_permission_inactive_user`, `test_auth_refresh`, `test_login_rate_limiter`, `test_oidc_*` | permission precedence (user override > role > deny), seed idempotency, JWT refresh, per-router auth deps, OIDC config/flow |
| **Persistence** | `test_base_repository_*`, `test_credentials_service*`, `test_retention_service`, `test_run_service_*`, `test_run_inputs_seeding`, `test_inventory_converter`, `test_user_preference_service`, `test_templates_*` | repository queries/commits, credential encryption + visibility, run trigger/list/delete/approval, retention purge |
| **Infra / cross-cutting** | `test_service_factory`, `test_safe_urls`, `test_safe_hosts`, `test_secret_fields`, `test_production_hardening`, `test_health_ready`, `test_redis_cache_service`, `test_hatchet_workers`, `test_plugin_registry_capabilities`, `test_filesystem_artifact_*` | DI wiring, SSRF/loopback URL guards, secret redaction, prod secret guards, cache, worker registration, plugin registry, artifact store |

### 4.2 Integration tests (`tests/integration/`, 68 tests, 10 modules)

Opt-in, against real lab systems. `xfail` markers on the git device-discovery
tests clear once a `devices/*.yaml` file is added to the lab Gitea repo.

| Module | Tests | Area / what it exercises |
|--------|:---:|--------------------------|
| `test_db_bootstrap.py` | 9 | `init_db()` creates all tables, idempotent re-run, no schema drift vs models, `ping_database`, declared indexes present |
| `test_repositories_crud.py` | 7 | real-Postgres round-trips: credential encryption (`LargeBinary`), JSON columns, unique constraints, server-default timestamps, RBAC precedence |
| `test_run_persistence.py` | 5 | `WorkflowRun` / `WorkflowStepResult` lifecycle, FK cascade on run delete, metadata-vs-content split (row vs `FilesystemArtifactService`) |
| `test_nautobot_inventory.py` | 14 | `NautobotSourceService`: connection, `preview_inventory` (all / status / tag / location / AND / not-equals), `resolve_devices_by_ids`, name search, device details + attribute bag, custom-field catalog, bad-token error, Redis bulk cache (skipped w/o Redis). Expected counts derived from `nautobot-baseline.yaml`. |
| `test_git_service.py` | 9 | `GitRepositoryService` CRUD, live clone / `open_or_clone` idempotency / pull-reports-zero, branches+commits, content search, wrong-token `GitCommandError`, offline local clone/commit/push fallback |
| `test_workflow_steps_netmiko.py` | 6 | direct executor calls on a real Cisco IOS device: `reachable` (ok + unreachable), `run-command` (read-only, TextFSM, **pooled-session reuse**), `get-device-configs` (running / both), unknown-credential error |
| `test_workflow_steps_nautobot.py` | 5 | `get-nautobot-devices` (filter → 54, static → exact ids), `get-nautobot-attributes` (custom-fields bag), misconfig → `ValueError`. Doubles as coverage of `resolve_nautobot_credentials` (credential-backed source config). |
| `test_workflow_steps_git.py` | 5 | `git-clone` / `git-pull` (0 commits) / `get-git-devices` outcomes + metadata, missing / inactive `git_repository_id` behaviour |
| `test_workflow_run_end_to_end.py` | 4 | full `StepRunner.execute_all`: Nautobot filter → reachable; static device → run-command → get-device-configs; git-devices → reachable; failure propagation (bad credential ⇒ downstream `skipped`, run `False`) |
| `test_mutations_optin.py` | 4 | Phase-2 writes (`@pytest.mark.mutations`, needs `--run-mutations`): `git-push` to a scratch branch with teardown; `deploy_config` / `upload_config` / `add_to_nautobot` scaffolded + skipped |

---

## 5. Regression guards & lint (not under `tests/`)

From `backend/`:

```bash
python scripts/check_asyncio_run.py        # no asyncio.run() in routers
python scripts/check_http_500_leaks.py     # no raw exception text in 5xx HTTPException
python scripts/check_router_repositories.py # routers don't import repositories
python scripts/check_text_sql.py           # no sqlalchemy.text() outside the allow-list
ruff check .
```

---

## 6. Common mistake

Dozens of collection errors like `ModuleNotFoundError: No module named 'core'`
⇒ you're not using the project `.venv`. Activate `../.venv` (or run
`../.venv/bin/python -m pytest`); imports are wired via `tests/conftest.py`.
