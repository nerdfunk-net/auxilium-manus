# Plan: Reach ≥ 80 % Backend Test Coverage

**Status:** in progress — Phase 0 ✅, Phase 1 ✅, Phase 2 ✅, Phase 3 ✅ (2026-08-30); suite at 74.7 %
**Owner:** backend
**Created:** 2026-08-30
**Scope:** `backend/` pytest suite (`tests/unit`), measured by `pytest-cov` with the
config already in `backend/pyproject.toml` (`[tool.coverage.run] source = ["."]`,
`omit = ["tests/*", "migrations/*", "scripts/*", ".venv/*"]`).

---

## 1. Current state (baseline)

Measured on 2026-08-30, `1097 passed`:

| Metric | Value |
|---|---|
| Total statements | 22 230 |
| Covered | 13 507 |
| Missing | 8 723 |
| **Line coverage** | **60.76 %** |

Reproduce:

```bash
cd backend
../.venv/bin/python -m pytest --cov --cov-report=term-missing
# machine-readable:
../.venv/bin/python -m pytest --cov --cov-report=json   # -> backend/coverage.json (git-ignored)
```

### Gap math

To hit 80 % at the current statement count we must cover
`0.80 * 22 230 - 13 507 ≈ 4 277` **additional statements**. Test files are in
`omit`, so writing tests barely moves the denominator — every newly-exercised
production line is net progress. Target **+4 450** covered statements to land at
~80.8 % with margin for churn.

---

## 2. Where the gap is

Coverage aggregated by package (statements ≥ 30, sorted by missing lines):

| Missing | Cov % | Stmts | Package |
|---:|---:|---:|---|
| 1 449 | 24.1 | 1 908 | `services/nautobot` |
| 1 365 | 30.6 | 1 967 | `services/git` |
| 705 | 23.0 | 916 | `services/sources` |
| 587 | 34.3 | 894 | `routers/sources` |
| 298 | 75.7 | 1 225 | `workflow_steps/common` |
| 266 | 67.9 | 828 | `services/execution` |
| 241 | 51.2 | 494 | `hatchet/workflows` |
| 237 | 42.8 | 414 | `routers/git` |
| 208 | 15.4 | 246 | `services/cache` |
| 125 | 75.2 | 504 | `services/network` |
| 117 | 40.3 | 196 | `services/credentials` |
| 117 | 21.5 | 149 | `workflow_steps/filter_output` |
| 110 | 23.1 | 143 | `workflow_steps/merge_content` |
| 103 | 84.7 | 675 | `services/workflow_context` |
| 92 | 43.6 | 163 | `workflow_steps/update_nautobot_device` |
| 91 | 62.9 | 245 | `services/workflow` |
| 82 | 28.7 | 115 | `routers/oidc.py` |
| 81 | 28.9 | 114 | `workflow_steps/update_content` |
| 69 | 30.3 | 99 | `workflow_steps/get_nautobot_attributes` |
| 63 | 10.0 | 70 | `utils/inventory_converter.py` |
| 57 | 0.0 | 57 | `hatchet/dynamic_worker.py` |
| 56 | 23.3 | 73 | `repositories/inventory_repository.py` |
| 52 | 25.7 | 70 | `workflow_steps/reachable` |
| 48 | 0.0 | 48 | `core/cert_installer.py` |

### Worst single files

| Missing | Cov % | Stmts | File |
|---:|---:|---:|---|
| 316 | 11.2 | 356 | `services/git/file_service.py` |
| 254 | 13.0 | 292 | `services/nautobot/devices/interface_workflow.py` |
| 241 | 0.0 | 241 | `services/git/debug_service.py` |
| 193 | 25.5 | 259 | `routers/sources/ise/ops.py` |
| 187 | 16.1 | 223 | `services/git/operations.py` |
| 177 | 11.1 | 199 | `services/cache/redis_cache_service.py` |
| 176 | 14.1 | 205 | `services/nautobot/devices/update.py` |
| 170 | 7.1 | 183 | `services/nautobot/resolvers/device_resolver.py` |
| 145 | 13.2 | 167 | `services/sources/nautobot/persistence_service.py` |
| 129 | 14.0 | 150 | `services/nautobot/devices/creation.py` |
| 128 | 34.4 | 195 | `services/git/service.py` |
| 127 | 29.4 | 180 | `services/sources/nautobot/query_service.py` |
| 126 | 22.2 | 162 | `services/sources/nautobot/evaluator.py` |
| 125 | 30.6 | 180 | `routers/sources/nautobot/ops.py` |
| 124 | 20.0 | 155 | `routers/sources/nautobot/crud.py` |
| 117 | 0.0 | 117 | `services/git/cache.py` |
| 119 | 9.2 | 131 | `services/nautobot/resolvers/metadata_resolver.py` |

**Read:** ~65 % of the deficit lives in four subsystems — Nautobot integration,
Git integration, the `sources/*` query/persistence layer, and their routers.
Those are external-I/O-heavy, which is why they were skipped; they need a
deliberate mocking strategy (Section 4), not incidental coverage.

---

## 3. Phased plan

Each phase is independently shippable and raises the floor. Percentages are the
target for that package after the phase. "Δcov" = estimated additional covered
statements.

### Phase 0 — Tooling & guard rails (0.5 day) — ✅ done 2026-08-30

No coverage change; makes the rest measurable and non-regressing.

1. ✅ Ratchet threshold added to `backend/pyproject.toml` `[tool.pytest.ini_options]`:
   `addopts = "-q --cov --cov-report=term-missing --cov-fail-under=70"`.
   Started at the current floor (60); raised to **65** after Phase 1 (66.8 %),
   **70** after Phase 2 (71.3 %), **74** after Phase 3 (74.7 %). Raise again after
   every phase so coverage can only go up. Running a subset of tests? Add
   `--no-cov` to skip the whole-suite threshold check.
2. ✅ `fakeredis==2.37.1` added to `backend/requirements-dev.txt` (needed for Phase 4).
3. ⏳ CI: deferred — the repo has no `.github/workflows/` yet. When CI is added,
   run `pytest` (which now enforces `--cov-fail-under`) on every PR and publish
   `coverage.json` / `htmlcov/` as a build artifact. `coverage.json` is git-ignored.
4. Document the per-package target table below in the PR description so reviewers
   can see the ratchet.

### Phase 1 — Nautobot service layer → 80 % (3–4 days) · Δcov ≈ +1 070 — ✅ done 2026-08-30

Files: `services/nautobot/resolvers/*`, `services/nautobot/managers/*`,
`services/nautobot/devices/*`, `services/nautobot/client.py`,
`services/nautobot/common/*`.

- Unit-test resolvers/managers against a **`MagicMock` `NautobotService`** whose
  `graphql()` / `rest()` return canned dict payloads. No network.
- `common/validators.py` + `common/utils.py` are pure functions — table-driven
  tests, cheap 100 %.
- `devices/interface_workflow.py`, `devices/update.py`, `devices/creation.py`:
  drive the `DeviceCommonService` facade with mocked resolver/manager return
  values; assert the GraphQL/REST mutation payloads that get built and the
  error branches (`is_valid_uuid` false, missing status, etc.).
- Target: `services/nautobot` 24 % → 80 %.

**Result:** `services/nautobot` **24 % → 94 %** (1908 stmts, 111 missing;
Δcov ≈ +1 338, ahead of the +1 070 estimate). Full-suite line coverage
60.8 % → **66.8 %**; `1097 → 1373` tests pass. New test modules (fixtures kept
inline rather than under `tests/unit/fixtures/nautobot/` — the canned payloads
are small and local to each test):

| Module | Covers |
|---|---|
| `test_nautobot_common_validators.py` | `common/validators.py` → 100 % |
| `test_nautobot_common_utils.py` | `common/utils.py` → 100 % |
| `test_nautobot_common_exceptions.py` | `common/exceptions.py` → 100 % |
| `test_nautobot_resolvers.py` | base/device/metadata/network resolvers (86–100 %) |
| `test_nautobot_managers.py` | ip/interface/prefix/device managers (96–100 %) |
| `test_nautobot_client.py` | `client.py` → 90 % (httpx pools + validator mocked) |
| `test_nautobot_devices_common_facade.py` | `devices/common.py` → 100 %, `metadata_service.py` → 100 % |
| `test_nautobot_devices_query.py` | `devices/query.py` + `attribute_bag.py` → 100 % |
| `test_nautobot_interface_workflow.py` | `devices/interface_workflow.py` → 93 % |
| `test_nautobot_device_creation.py` | `devices/creation.py` → 91 % |
| `test_nautobot_device_update.py` | `devices/update.py` → 94 % |
| `test_nautobot_types_and_bound_client.py` | `devices/types.py` → 100 %, `credentials_bound_client.py` → 100 % |

Residual misses are `except Exception` / `exc_info=True` logging branches in the
resolvers and a few defensive guards in the three `devices/*` orchestrators —
left for the Phase 7 sweep.

### Phase 2 — Git service layer → 80 % (3–4 days) · Δcov ≈ +965 — ✅ done 2026-08-30

Files: `services/git/file_service.py`, `operations.py`, `service.py`,
`cache.py`, `debug_service.py`, `repository_service.py`, `csv_service.py`,
`device_service.py`, `content_search_service.py`.

- For `service.py` / `operations.py` / `sync.py`: build **real throwaway git
  repos in `tmp_path`** (`git init`, commit a file, add a bare remote as
  `file://`) and exercise clone/pull/push/commit/fetch/status for real. This is
  fast and covers the happy paths + conflict/ahead-behind branches honestly.
- `file_service.py` (browsing, history, directory tree, content parsing): run
  against the same `tmp_path` repo; assert tree shape, history entries, binary
  vs text detection, and every `raise_internal_server_error(...)` branch by
  pointing at a missing path / bad ref.
- `cache.py` / `debug_service.py` (currently 0 %): mock the filesystem/redis
  bits they touch; these are small and mechanical.
- `repository_service.py`: CRUD over in-memory SQLite (`GitRepository` table),
  cover `_to_dict()` shape and uniqueness/`not found` errors.
- Target: `services/git` 31 % → 80 %; `routers/git` covered in Phase 5.

**Result:** `services/git` **31 % → 80 %** (1967 stmts, 393 missing; Δcov ≈ +972,
on the +965 estimate). Full-suite line coverage 66.8 % → **71.3 %**;
`1373 → 1509` tests pass. `--cov-fail-under` raised **65 → 70**.

Shared helper `tests/unit/_git_repo_builder.py` builds real throwaway repos
(`git init`, seeded commits, `file://` bare remote). New test modules:

| Module | Covers |
|---|---|
| `test_git_repository_service.py` | `repository_service.py` → 81 % (SQLite CRUD) |
| `test_git_cache_service.py` | `cache.py` → 91 % (real repo + mock cache) |
| `test_git_service_engine.py` | `service.py` → 79 % (real `file://` clone/pull/push/commit/fetch) |
| `test_git_file_service.py` | `file_service.py` → 76 % (search/history/tree/content, path-escape + binary branches) |
| `test_git_csv_service.py` | `csv_service.py` → 91 % |
| `test_git_device_service.py` | `device_service.py` → 98 % |
| `test_git_version_control_service.py` | `version_control_service.py` → 93 % |
| `test_git_operations_service.py` | `operations.py` → 74 % (sync/remove/record/status/info) |
| `test_git_debug_service.py` | `debug_service.py` → 72 % (read/write/delete/push roundtrip/diagnostics) |
| `test_git_misc_helpers.py` | `shared_utils.py` → 100 %, `env.py` → 93 % |

`config.py` (71 %) is exercised transitively via `set_git_author` in the service
tests. The outbound-URL guard (`validate_git_remote_url`) is patched to a no-op in
`test_git_service_engine.py` so `file://` remotes work; everywhere else the real
policy still applies. Residual misses: `except`/re-raise branches in
`repository_service.py`, `auth.py` credential-manager paths (needs the RBAC
credential stack — deferred to Phase 4), and `file_service.get_commit_files`'s
no-`file_path` branch (a latent `from config import settings` import that always
raises — left as a pre-existing bug, not masked by a test).

### Phase 3 — `sources/*` query & persistence → 80 % (2–3 days) · Δcov ≈ +520 — ✅ done 2026-08-30

Files: `services/sources/nautobot/{query_service,persistence_service,evaluator,source_service,live_query_mixin,metadata_service}.py`.

- `evaluator.py` is largely pure predicate/filter logic — table-driven tests,
  high yield.
- `query_service.py` / `live_query_mixin.py`: mock the Nautobot client;
  parametrise over filter combinations and pagination.
- `persistence_service.py`: in-memory SQLite; assert upsert/delete/diff
  behaviour against seeded rows.
- Target: `services/sources` 23 % → 80 %.

**Result:** `services/sources` **23 % → 93 %** (916 stmts, 65 missing; Δcov ≈ +640,
ahead of the +520 estimate). Full-suite line coverage 71.3 % → **74.7 %**;
`1509 → 1618` tests pass. `--cov-fail-under` raised **70 → 74**. Two Phase-4
targets fell out for free: `utils/inventory_converter.py` **10 % → 97 %** and
`repositories/inventory_repository.py` **22 % → 95 %** (the persistence tests run
against a real `InventoryRepository` on in-memory SQLite).

| Module | Covers |
|---|---|
| `test_inventory_converter.py` | `utils/inventory_converter.py` → 97 % (tree → LogicalOperation, version-2 guards) |
| `test_sources_nautobot_evaluator.py` | `evaluator.py` → 96 % (AND/OR/NOT combine, native vs client negation, custom-field) |
| `test_sources_nautobot_query_service.py` | `query_service.py` → 94 %, `live_query_mixin.py` → 93 % (cache-first filters, live GraphQL, CIDR/custom-field) |
| `test_sources_nautobot_persistence_service.py` | `persistence_service.py` → 82 %, `inventory_repository.py` → 95 % (SQLite CRUD, scopes, group rename, access control) |
| `test_sources_nautobot_metadata_service.py` | `metadata_service.py` → 97 % (custom-field transform, field-value endpoints) |
| `test_sources_nautobot_source_service.py` | `source_service.py` → 94 % (preview combine logic, saved-inventory resolution) |
| `test_sources_nautobot_export_and_connection.py` | `export_service.py` → 100 %, `connection.py` → 100 % |

Residual misses in `persistence_service.py` are the `except Exception → log + return []/raise`
guards; the package as a whole is at 93 %.

### Phase 4 — Redis cache + smaller service gaps → 85 % (2 days) · Δcov ≈ +540

- `services/cache/redis_cache_service.py` (15 %): inject **`fakeredis.FakeRedis`**
  (or a `MagicMock` client) and test get/set/delete/TTL/locks/namespace key
  building and the JSON (de)serialisation + error paths.
- `services/credentials/credentials_service.py` (40 %): in-memory SQLite +
  mocked encryptor; cover visibility scoping, `CredentialNotFoundError`, and the
  generic/token/ssh branches.
- `utils/inventory_converter.py` (10 %) and
  `repositories/inventory_repository.py` (22 %): pure/near-pure — fixture in,
  expected structure out.
- `service_factory.py` (50 %): assert each `build_*` returns a wired instance
  with mocked `settings`.

### Phase 5 — Routers via `TestClient` → 80 % (3 days) · Δcov ≈ +900

Files: `routers/sources/**`, `routers/git/**`, `routers/oidc.py`,
`routers/templates.py`, `routers/workflows.py`, `routers/workflow_*` , plus the
already-partly-covered `routers/*`.

- Reuse the established pattern in `tests/unit/test_credentials_router.py`:
  bare `FastAPI()`, `include_router(...)`, override `verify_token` /
  `get_current_user` / `get_db`, monkeypatch `RBACService.has_permission`, and
  override the router's `_service` dependency with a `MagicMock`.
- One test per route for: 200 happy path, 401/403 (permission denied),
  404 (service raises `NotFoundError`), 400 (validation), and the
  `raise_internal_server_error` → sanitized `{message, error_id}` shape.
- Run `python scripts/check_http_500_leaks.py` as part of this phase — router
  tests are the natural place to lock in the "no raw exception text in 5xx"
  rule.
- Target: `routers/sources` 34 % → 80 %, `routers/git` 43 % → 85 %,
  `routers/oidc.py` 29 % → 85 %.

### Phase 6 — Workflow steps & execution engine → 88 % (2–3 days) · Δcov ≈ +650

- `workflow_steps/common/*` (76 %): `content_resolver.py` and
  `git_repository_loader.py` are the misses — test resolution precedence, the
  `git_repository_id` → repo-dict path, and `ValueError`/`RuntimeError` raises.
- Under-covered executors: `filter_output` (22 %), `merge_content` (23 %),
  `update_content` (23 %), `update_nautobot_device` (44 %),
  `get_nautobot_attributes` (30 %), `reachable` (26 %). Follow the existing
  executor-test style (`tests/unit/test_*_executor.py`): build a
  `WorkflowContext` with fake devices, mock `device_sessions` / external
  services / `artifact_service` (`InMemoryArtifactService`), assert the returned
  `list[StepOutcome]` and the success/failure branch colours.
- `services/execution/step_runner.py` (69 %) and `hatchet/workflows/workflow_run.py`
  (68 %): cover fan-out (per-device child workflows), retry/step-state
  transitions, and the dispatch resolution added in `run_service` (published vs
  unpublished → `BackgroundTierRepository`).
- `hatchet/dynamic_worker.py` / `hatchet/worker_services.py` (0 %): at minimum
  import + smoke-test the registration/fingerprint-poll functions with mocked
  Hatchet client; full coverage is a stretch goal, not required for 80 %.

### Phase 7 — Sweep & ratchet to 80 % (1–2 days)

- Fill remaining `--cov-report=term-missing` gaps in already-high modules
  (`repositories/*`, `core/*`, `models/*`) — mostly error branches and
  `__repr__`/guard clauses.
- Explicitly `# pragma: no cover` only for genuinely unreachable defensive
  code, `if TYPE_CHECKING:` blocks, and `__main__` guards — keep this list
  short and reviewed.
- Raise `--cov-fail-under` to **80**.

---

## 4. Testing techniques by module type

| Module type | Technique | Reference in repo |
|---|---|---|
| Pure functions (validators, converters, evaluators) | Table-driven `unittest` cases | `tests/unit/test_*_validation*.py` |
| Repositories / DB services | In-memory SQLite, create only the needed `__table__`s | `tests/unit/test_run_service_run_inputs.py` |
| FastAPI routers | `TestClient` + `dependency_overrides` + mocked `_service` | `tests/unit/test_credentials_router.py` |
| Nautobot resolvers/managers | `MagicMock` `NautobotService`, canned `graphql()`/`rest()` payloads | `services/nautobot/**` CLAUDE.md section |
| Git services | Real `tmp_path` git repos + `file://` bare remotes | new — `tests/unit/fixtures/git/` |
| Redis cache | `fakeredis.FakeRedis` injected client | new — add `fakeredis` to `requirements-dev.txt` |
| Workflow-step executors | `WorkflowContext` + fake devices + `InMemoryArtifactService`, mock `device_sessions` | `tests/unit/test_add_pyats_testbed_executor.py`, `test_git_workflow_steps.py` |
| Hatchet workflows/workers | Mock `hatchet.client.hatchet`, patch `run_no_wait` / `event.push` | `tests/unit/test_run_service_*.py` |

**Rules to keep the suite fast and offline (per `tests/README.md`):**
no running PostgreSQL/Redis/Hatchet/Nautobot; all external I/O mocked;
`unittest` style; every test deterministic.

---

## 5. Estimated effort & trajectory

| Phase | Focus | Est. effort | Cum. Δcov | Projected total |
|---|---|---:|---:|---:|
| 0 | Tooling / ratchet | 0.5 d | 0 | 60.8 % |
| 1 | Nautobot services | 3–4 d | +1 070 (actual +1 338) | 65.6 % (actual **66.8 %**) |
| 2 | Git services | 3–4 d | +2 035 (actual +2 310) | 70.2 % (actual **71.3 %**) |
| 3 | `sources/*` layer | 2–3 d | +2 555 (actual +2 950) | 72.5 % (actual **74.7 %**) |
| 4 | Redis cache + small gaps | 2 d | +3 095 | 74.9 % |
| 5 | Routers | 3 d | +3 995 | 78.9 % |
| 6 | Workflow steps + engine | 2–3 d | +4 645 | 81.9 % |
| 7 | Sweep + ratchet to 80 | 1–2 d | — | ≥ 80 % |

**Total: ~17–22 engineer-days.** 80 % is mathematically reached during Phase 6;
Phases 1–5 alone get to ~79 %, so Phase 6 is the safety margin and Phase 7 locks
it in.

---

## 6. Per-package target table (the ratchet)

Raise `--cov-fail-under` after each phase; track packages here.

| Package | Baseline | Target | Phase | Achieved |
|---|---:|---:|---|---:|
| `services/nautobot` | 24 % | 80 % | 1 | **94 %** ✅ |
| `services/git` | 31 % | 80 % | 2 | **80 %** ✅ |
| `services/sources` | 23 % | 80 % | 3 | **93 %** ✅ |
| `services/cache` | 15 % | 85 % | 4 | — |
| `services/credentials` | 40 % | 88 % | 4 | — |
| `utils/inventory_converter.py` | 10 % | 90 % | 4 | **97 %** ✅ (Phase 3) |
| `repositories/inventory_repository.py` | 22 % | 90 % | 4 | **95 %** ✅ (Phase 3) |
| `routers/sources` | 34 % | 80 % | 5 | — |
| `routers/git` | 43 % | 85 % | 5 | — |
| `routers/oidc.py` | 29 % | 85 % | 5 | — |
| `workflow_steps/common` | 76 % | 92 % | 6 | — |
| `workflow_steps/filter_output` | 22 % | 90 % | 6 | — |
| `workflow_steps/merge_content` | 23 % | 90 % | 6 | — |
| `workflow_steps/update_content` | 23 % | 88 % | 6 | — |
| `workflow_steps/update_nautobot_device` | 44 % | 88 % | 6 | — |
| `workflow_steps/get_nautobot_attributes` | 30 % | 85 % | 6 | — |
| `workflow_steps/reachable` | 26 % | 80 % | 6 | — |
| `services/execution` | 68 % | 88 % | 6 | — |
| `hatchet/workflows` | 51 % | 82 % | 6 | — |
| **TOTAL** | **60.8 %** | **≥ 80 %** | 7 | — |

---

## 7. Out of scope / accepted exclusions

- `migrations/`, `scripts/`, `tests/` — already in `[tool.coverage.run] omit`.
- `hatchet/dynamic_worker.py`, `hatchet/worker_services.py`,
  `core/cert_installer.py` — process-lifecycle / OS-cert glue; smoke-import only,
  `# pragma: no cover` the un-runnable parts. Not counted toward package targets.
- Branch coverage (`--cov-branch`) — keep line coverage for the 80 % goal;
  revisit branch coverage as a follow-up once line coverage is stable.
- Integration tests (`tests/integration/`, `-m integration`) — opt-in, real
  devices; not part of the coverage number.

---

## 8. Definition of done

- [ ] `cd backend && ../.venv/bin/python -m pytest` passes with
      `--cov-fail-under=80` in `addopts`.
- [ ] No new `# pragma: no cover` outside the reviewed exclusion list in §7.
- [ ] `scripts/check_http_500_leaks.py`, `check_router_repositories.py`,
      `check_text_sql.py`, `check_asyncio_run.py`, `ruff check .` all clean.
- [ ] CI enforces the threshold on every PR and uploads the HTML report.
- [ ] This document's §6 table filled in with the achieved numbers.
