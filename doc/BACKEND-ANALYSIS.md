# Backend Analysis

**Date:** 2026-07-08
**Scope:** `backend/` measured against `CLAUDE.md`, `doc/WORKFLOW-STEPS.md`, and
`doc/WORKFLOW-STEPS-STYLE_GUIDE.md`. Frontend was inspected only where the workflow-step
style guide requires it (canvas node, config panels, dialogs, plugin UI registry).

**Verification performed:** full test suite executed (`python -m unittest discover -s tests`
→ **148 tests, all pass, 0.37s**), `ruff check .` executed (531 findings, breakdown below),
and every cross-registry consistency check (registry.yaml ↔ dispatch table ↔ backend
packages ↔ frontend directories ↔ plugin-ui-registry.ts) done by enumeration, not sampling.

---

## 1. Executive Summary

The backend is in **good architectural shape**. The layered Model → Repository → Service →
Router pattern is genuinely followed, routers are thin and consistently authenticated, the
workflow-step subsystem is exemplary in its consistency (all 20 steps correctly registered
in all four places, all executors conform to the documented contract), and the full test
suite passes.

The biggest problem is not the code — it is **CLAUDE.md itself**. Large parts of its
"Key File Locations", "Database Schema", "Authentication & Authorization", and "Tech Stack"
sections describe the legacy `cockpit/` application, not this backend. Anyone (human or AI)
following CLAUDE.md will look for RBAC tables, guard scripts, and Celery settings that do
not exist here.

Findings by severity:

| Severity | Count | Theme |
|----------|-------|-------|
| High     | 3     | CLAUDE.md/code drift (auth, schema, scripts); no authorization layer |
| Medium   | 6     | Layer-boundary violations, debug-endpoint error leakage, lint debt, missing test tooling |
| Low      | 7     | Naming inconsistencies, file-size overruns, style-guide gaps, dead directory |

---

## 2. Directory Structure vs. CLAUDE.md

### 2.1 Verdict: largely compliant

```
backend/
├── core/               ✅ config, database, auth, crypto, logging, safe_http_errors
│   └── models/         ✅ SQLAlchemy models split by domain, re-exported from __init__.py
├── models/             ✅ Pydantic request/response schemas per domain
├── repositories/       ✅ data access layer (one repo per domain)
├── services/           ✅ business logic, feature-grouped packages
├── routers/            ✅ thin HTTP layer, feature-grouped
├── workflow_steps/     ✅ one package per step + registry.yaml (matches WORKFLOW-STEPS.md)
├── hatchet/            ✅ worker, client, workflow_run.py, device_group_execution.py
├── migrations/         ✅ custom framework (base.py, runner.py, versions/)
├── tests/              ✅ 34 test modules
├── scripts/            ⚠️ only purge_retention.py — see finding 3.3
├── dependencies.py     ✅ FastAPI DI helpers
├── service_factory.py  ✅ service construction helpers
└── main.py             ✅ app + router registration only
```

The documented layer pattern (SQLAlchemy model → Pydantic model → repository → service →
router → registration in `main.py`) is observable end-to-end, e.g. the workflows domain:
`core/models/workflows.py` → `models/workflows.py` → `repositories/workflow_repository.py`
→ `services/workflow/workflow_service.py` → `routers/workflows.py` → `main.py:82`.

### 2.2 Findings

**[LOW] Repository layout is inconsistent.** Eight repositories are flat files
(`repositories/{domain}_repository.py`, per CLAUDE.md), but one lives in a sub-package:
`repositories/git/git_repository_repository.py`. Either flatten it or update CLAUDE.md to
allow sub-packages.

**[LOW] `BaseRepository` is used by only 1 of 9 repositories.**
`GitRepositoryRepository` extends `BaseRepository[GitRepository]`; the other eight
(`user_repository.py`, `workflow_repository.py`, `run_repository.py`, …) are standalone
classes. CLAUDE.md says "Use repository pattern (BaseRepository in
/backend/repositories/base.py)". The standalone repos are still clean ORM data-access
classes, so this is stylistic — but either adopt the base class consistently or drop the
claim from CLAUDE.md.

**[LOW] CLAUDE.md is internally inconsistent about router/service paths.** The layer
pattern section says `routers/{domain}.py`, while "Adding New Backend Endpoint" says
`routers/{domain}/{domain}.py` and `services/{domain}/{domain}/{domain}_service.py` (a
double-nested path that nothing uses). Reality is a sensible mix: flat routers for simple
domains, packages (`routers/git/`, `routers/sources/nautobot/`) for larger ones. Fix the
doc.

**[LOW] Dead directory: `backend/services/validation/`** contains only a stale
`__pycache__` — no `__init__.py`, no modules. Delete it or populate it.

---

## 3. CLAUDE.md Documentation Drift (the most important findings)

### 3.1 [HIGH] The documented authorization model does not exist

CLAUDE.md documents `require_permission("resource", "action")`, `verify_admin_token`, a
permission bitmask, and RBAC tables (`roles`, `permissions`, `role_permissions`,
`user_roles`, `user_permissions`).

Reality (`core/auth.py`, 69 lines): only `verify_token` (JWT decode) and
`get_current_user` (active-user lookup) exist. The JWT *is* issued with a `permissions`
claim (`services/auth/auth_service.py:44`), but **no code anywhere reads or enforces it**
— grep for permission checks in `routers/` and `services/` returns nothing.

Consequence: **every authenticated user can do everything** — manage credentials, run
commands on network devices via `/netmiko/run-commands`, push to git, change settings, and
call debug endpoints. For a NetDevOps tool that holds device SSH credentials this is a
real security gap once more than one user exists. Either implement `require_permission`
(the bitmask is already in the token) or rewrite the CLAUDE.md auth section to describe
the current single-tier model honestly.

### 3.2 [HIGH] "Key File Locations" and "Database Schema" describe a different app

CLAUDE.md lists `core/models/audit.py`, `rbac.py`, and a `settings.py` containing
`AgentsSetting`, `CacheSetting`, `CelerySetting`, `CheckMKSetting`, `GitSetting`,
`NautobotDefault`, `NautobotSetting`, `SettingsMetadata`, plus tables like
`user_profiles`, `snmp_mapping`, `login_credentials`, and claims "40+ tables".

Reality: `core/models/` contains `base, credentials, git, inventories, runs, settings,
templates, users, workflows`; `settings.py` defines a single generic `Setting` model; and
there are exactly **9 tables**: `credentials`, `git_repositories`, `workflow_runs`,
`workflow_step_results`, `inventories`, `settings`, `templates`, `workflows`, `users`.

The described files/tables exist in the legacy `cockpit/` app in this repo. The CLAUDE.md
sections were evidently carried over and never updated.

### 3.3 [HIGH] The four regression guard scripts do not exist in this backend

CLAUDE.md's Development Workflow instructs running (from `backend/`):

```
python scripts/check_asyncio_run.py
python scripts/check_http_500_leaks.py
python scripts/check_router_repositories.py
python scripts/check_text_sql.py
```

`backend/scripts/` contains only `purge_retention.py`. The guard scripts live in
`cockpit/backend/scripts/`. Manual equivalents of all four checks were run for this
analysis (results in §4) and the codebase passes three of them — ironically the one
violation found (`check_router_repositories`) would have been caught if the script were
present. **Recommendation:** copy/adapt the four scripts into `backend/scripts/`; they are
small, self-contained AST checkers and the codebase is already nearly clean against them.

### 3.4 [MEDIUM] Tech-stack section overstates the stack

`requirements.txt` (16 pinned packages) contains **no** Celery/Beat, Ansible, Alembic,
CheckMK client, or OIDC library — all listed in CLAUDE.md's Tech Stack. Migrations use a
custom framework (`migrations/base.py` + `runner.py`), not Alembic (MIGRATION_SYSTEM.md
gets this right; the Tech Stack line does not). Also missing from requirements: any test
runner (see §6.2).

---

## 4. Router Analysis

21 router modules, 106 routes total. Overall: **well implemented.**

### 4.1 What is done right

- **Thin routers, service delegation.** Spot-checked `workflows.py`, `templates.py`,
  `git/debug.py`, `netmiko.py`, `sources/nautobot/ops.py`: routes validate, call a
  service, map domain exceptions to HTTP codes. No business logic found in routers.
- **Authentication coverage: 100%.** Every route is protected, either per-route
  (`Depends(get_current_user)`) or router-wide
  (`APIRouter(dependencies=[Depends(get_current_user)])` — e.g. `workflows.py:25`,
  `cache_settings.py:22`, `netmiko.py:35`). No unauthenticated endpoint exists except
  `/health` and the two auth routes, which is correct.
- **5xx sanitization rule respected.** `core.safe_http_errors.raise_internal_server_error`
  is used in all 11 routers that handle unexpected errors. Every `detail=str(exc)`
  occurrence (21 sites) is on a **4xx** response (400/403/404/409) mapping domain
  exceptions — explicitly allowed by the CLAUDE.md rule, which targets 5xx only.
- **No `sqlalchemy.text()` anywhere** in routers, services, or repositories (the
  `SELECT 1` health check exemption in `core/database.py` aside). No f-strings in raw SQL.
- **No `asyncio.run()`** in routers/services/steps/hatchet code.
- **No f-string logging, no `print()`** in production code — the `%s` lazy-logging
  convention is followed throughout.
- **Pydantic at the boundary.** Request bodies and `response_model` are used
  consistently; `netmiko.py` additionally validates command lists, credential type, and
  decryption failures with precise 400/404 responses.
- **DI is clean**: `dependencies.py` / `service_factory.py` centralize construction;
  routers never instantiate infrastructure directly.

### 4.2 Findings

**[MEDIUM] `routers/sources/git/ops.py` violates two layer boundaries.**
1. It imports and uses `SettingsRepository` directly (`ops.py:17`, used in
   `_load_source_config`) — CLAUDE.md: routers must not bypass the service layer, and the
   absent `check_router_repositories.py` guard exists precisely for this.
2. It imports **private** functions from a service:
   `from services.sources.git.git_source_service import _clone_or_pull, _remove_and_clone`
   (`ops.py:19-23`). Underscore-prefixed names are module-internal by convention; promote
   them to public service methods or wrap them.

**[MEDIUM] `routers/git/debug.py` leaks raw exception details in response bodies.**
`_debug_error()` (`debug.py:20-29`) returns `str(e)` and `type(e).__name__` to the client
inside a JSON body. This sidesteps the letter of the 5xx rule (it's not an
`HTTPException(detail=…)`) but violates its intent — internal paths, git remotes, and
library error text reach the client. Combined with §3.1 (no authorization), every
authenticated user can invoke these diagnostics. Recommend: gate debug routes behind an
admin check and log details server-side, returning only `{message, error_id}`.

**[LOW] Two routers keep large inline helpers.** `routers/sources/nautobot/ops.py`
(365 lines) and `crud.py` (326 lines) are the biggest routers and contain
request-shaping helpers that could move into their services. Not urgent — routes
themselves remain thin.

---

## 5. Workflow Steps vs. WORKFLOW-STEPS.md

This is the **strongest part of the backend**. All checks below were done by full
enumeration over all 20 steps.

### 5.1 Registration consistency — 20/20 ✅

The same 20 step ids appear, with zero mismatches, in:

1. `workflow_steps/registry.yaml` (20 entries, `schema_version: 1`)
2. `services/execution/step_registry.py` `STEP_REGISTRY` (20 entries)
3. `backend/workflow_steps/{snake_case}/` packages (20 directories + `common/`)
4. `frontend/src/components/features/workflow-steps/{kebab-case}/` (20 dirs + `shared/`)
5. `frontend/src/lib/plugin-ui-registry.ts` `PLUGIN_UI_REGISTRY` (20 entries)

### 5.2 Backend contract compliance ✅

- **Executor signature:** all 20 `executor.py` modules expose exactly one
  `async def execute(*, config, context, run, artifact_service, node_id) -> list[StepOutcome]`
  with keyword-only parameters, as specified.
- **`config.py`:** present in all 20 packages; served by
  `GET /api/workflow-steps/{plugin_id}/get-config` (`routers/workflow_steps.py:61`)
  exactly as documented.
- **Start/finish logging rule:** 17/20 executors contain ≥2 `logger.info` calls. The three
  git steps (`git_clone`, `git_pull`, `git_push`) have zero in their thin wrappers — which
  is the **documented** pattern: the shared helper
  `workflow_steps/common/git_workflow_step.py` logs start (`:130`) and finish (`:171`)
  once for all three. Fully compliant.
- **Dispatch table purity:** `step_registry.py` is imports + one dict — no business logic.
- **Error contract:** spot-checked executors raise `ValueError` for config errors and
  `RuntimeError` for execution failures per spec.
- **Fan-out/fan-in:** implemented as documented — `StepRunner.execute_all` returns a
  `FanOutSignal` (with `join_node_id`), `hatchet/workflows/device_group_execution.py`
  exists for child execution, `services/workflow_context/merge.py` implements
  `merge_fan_out_contexts`, and `fan_in` is a near pass-through executor. The doc and the
  code agree, including the first-child-wins scalar-merge caveat.
- **Outcome naming:** all steps use the standard names (`success`/`failure`,
  `match`/`mismatch`/`failure` for `compare-data`). `route-on-attribute` uses dynamic
  route names (`ios`, `nxos`, `unmatched`) — handled by the documented "anything else →
  sky" fallback, so compliant.
- **Tests:** 22 of 34 test modules target step executors/context/merge logic directly —
  the step subsystem is the best-tested part of the backend.

### 5.3 Findings

**[MEDIUM] The "only StepRunner imports workflow_steps" boundary is broken twice.**
WORKFLOW-STEPS.md: *"External code (routers, other services) must never import
`workflow_steps` packages directly."* Violations:

1. `routers/workflow_update_attribute.py:18-19` imports
   `workflow_steps.common.attribute_path` and `workflow_steps.common.attribute_regex`
   (for the config-panel probe endpoints).
2. `services/artifacts/sinks/git_sink.py:14` imports
   `workflow_steps.common.device_template.sanitize_relative_path`.

Both import shared *helpers*, not executors, and the dependency direction is arguably
fine — but the rule as written is absolute. Either move genuinely shared helpers out of
`workflow_steps/common/` into `services/` (or a `common/` top-level package), or amend the
doc to exempt `workflow_steps/common/`.

**[LOW] One directory/id naming mismatch.** `get-nautobot-attributes` lives in
`workflow_steps/nautobot_attributes/` instead of `get_nautobot_attributes/`. The registry
`directory:` field makes this work, but it breaks the documented convention that the
directory is the snake_case form of the id — and it is the only one of 20 that does.

**[LOW] Fan-out safety notes are not in registry.yaml.** WORKFLOW-STEPS.md asks that
steps mutating shared external resources "document [their] fan-out behaviour in
registry.yaml". The `store-artifact` and git-step entries carry no such note; the safety
table lives only in the doc. Cheap to add to the descriptions/metadata.

---

## 6. Code Quality

### 6.1 File-size and structure rules

- 29,865 lines of backend Python. Most files are well under the 800-line limit.
- **Two violations of the 800-line max:** `services/git/file_service.py` (871) and
  `services/sources/nautobot/query_service.py` (807). Next-largest are fine
  (`services/git/service.py` 745, `interface_workflow.py` 704).
- `routers/git/main.py`'s own docstring records the good history here: a 1,790-line
  monolith was split into 5 focused modules.

### 6.2 [MEDIUM] Test tooling is not declared

34 test modules, stdlib `unittest` style, **148 tests — all pass** via
`python -m unittest discover -s tests`. But:

- `pytest` is neither installed in the venv nor declared anywhere, even though the global
  Python testing rules mandate pytest + coverage measurement. There is no
  `requirements-dev.txt` and no `[tool.pytest]`/coverage config in `pyproject.toml`.
- Coverage is therefore unmeasured; the 80% target is unverifiable.
- Test distribution is lopsided: excellent on workflow steps and context/merge logic,
  **zero** tests on routers (no FastAPI `TestClient` tests), auth, repositories, or the
  git service layer (the largest service package).

### 6.3 [MEDIUM] Lint debt: 531 ruff findings, concentrated in ported code

`ruff check .` (config: `select = ["E","F","I","UP","B"]`, `target-version = "py39"`):

| Count | Rule | Meaning |
|-------|------|---------|
| 179 | UP006 | `List`/`Dict` instead of `list`/`dict` |
| 164 | UP045 | `Optional[X]` instead of `X \| None` |
| 56  | E501  | line too long |
| 51  | UP031 | `%`-formatting instead of f-string/format (non-logging) |
| 45  | UP035 | deprecated `typing` imports |
| 25  | B904  | `raise` without `from` inside `except` |
| 11  | I001/F401/F811 | auto-fixable import issues |

The debt clusters in code ported from cockpit: `services/nautobot/managers/vm_manager.py`
(61), `services/git/file_service.py` (59), `models/git_repositories.py` (31),
`services/nautobot/devices/interface_workflow.py` (30). Newer code (workflow_steps,
execution, routers) is nearly clean. The 25 B904s are the only correctness-adjacent ones
(exception-chaining). Note also `target-version = "py39"` while the project venv runs
Python 3.14 — worth raising to at least `py312`, which would also make the UP-series
fixes unambiguous.

### 6.4 Positive quality observations

- `core/crypto.py` + `cryptography` pin: credential passwords are encrypted at rest and
  decrypted only through `CredentialsService`; no secrets hardcoded anywhere checked.
- All SQLAlchemy models have `created_at`/`updated_at` and indexes; everything is
  exported from `core/models/__init__.py` as required.
- `core/logging_config.py` implements exactly the dual-handler (`app.log`/`worker.log`)
  scheme WORKFLOW-STEPS.md describes.
- `lifespan` startup is tidy: `init_db()`, initial admin, plugin registry load, Nautobot
  client lifecycle, cache construction — no hidden globals beyond `service_factory`.

---

## 7. Frontend Style-Guide Compliance (workflow steps only)

### 7.1 Canvas node — compliant ✅

`workflow-node.tsx` matches the guide: `NODE_WIDTH_CLASS = "w-80"`,
`NODE_HEIGHT_CLASS = "h-32"` as constants (no per-step overrides anywhere);
`TARGET_HANDLE_CLASS` defined once (slate); title uses `text-sm font-semibold
leading-snug` with **no** `truncate`; description uses `line-clamp-2`; outcome colours
and `nodeIconsByKind`/`nodeIconsByType` resolution are centralized; the fan-out badge is
teal with the `Split` icon per spec. There is one `data.kind === "fan-in"` branch
(`workflow-node.tsx:105`) — it only adds an info tooltip, not a layout fork, so it is a
technical-but-harmless deviation from the "no kind branches" rule.

No `sky-`/`blue-` classes exist anywhere under
`components/features/workflow-steps/` — palette rule holds.

### 7.2 Dialogs — [LOW] gaps

- The teal gradient header (`from-teal-600 to-teal-500`) appears in only **1 of 7** step
  dialogs (`update-nautobot-device/update-device-dialog.tsx`). The reference step's own
  `preview-dialog.tsx` has no card header at all.
- The guide's *"Always include `<DialogHeader className="sr-only">`"* rule is met by
  **0 of 7** dialogs (they use visible `DialogHeader`s, which is fine for accessibility
  but not what the guide prescribes).
- `focus:ring-teal-400/40` appears only 3× across all step components.

Either the dialogs should be aligned or the guide relaxed — currently the guide describes
an ideal only one step implements fully.

---

## 8. Prioritized Recommendations

1. **Fix CLAUDE.md** (§3.1–3.4): rewrite Key File Locations, Database Schema, Auth, and
   Tech Stack to describe *this* backend, not cockpit. This is the highest-leverage fix —
   every future AI/human session inherits these errors.
2. **Decide on authorization** (§3.1): the permission bitmask is already in the JWT;
   implement `require_permission` (start with `netmiko`, `credentials`, `settings`, git
   debug routes) or explicitly document the single-tier model.
3. **Port the four guard scripts** from `cockpit/backend/scripts/` into
   `backend/scripts/` and wire them into the workflow (§3.3); they would already catch
   finding §4.2-1.
4. **Fix the two layer violations**: `routers/sources/git/ops.py` (repository access +
   private-function imports) and decide the `workflow_steps.common` import policy (§5.3).
5. **Sanitize `routers/git/debug.py` responses** and admin-gate the debug endpoints (§4.2).
6. **Add dev tooling**: `requirements-dev.txt` with pytest (+ pytest-cov), measure
   coverage, and add first `TestClient`-based router tests (auth, workflows, netmiko).
7. **Burn down lint debt** in the four ported hot-spot files; fix the 25 B904s first;
   raise `target-version` to match the actual runtime.
8. Low-priority cleanups: delete `services/validation/`, rename
   `nautobot_attributes/` → `get_nautobot_attributes/`, split the two >800-line services,
   align or relax the dialog style rules.

---

## 9. Compliance Scorecard

| Standard | Verdict |
|---|---|
| Layered backend pattern (Model→Repo→Service→Router) | ✅ Followed (1 router violation) |
| Directory structure per CLAUDE.md | ✅ Mostly (doc itself inconsistent) |
| Router auth coverage | ✅ 100% authenticated |
| Permission/RBAC enforcement per CLAUDE.md | ❌ Not implemented |
| 5xx error sanitization | ✅ (1 gray-area leak in debug router) |
| No `text()` / raw SQL / `asyncio.run` / f-string logging | ✅ Clean |
| Guard scripts available & passing | ❌ Scripts missing (manual checks: 3/4 pass) |
| WORKFLOW-STEPS.md: registry/dispatch/executor contract | ✅ 20/20 fully consistent |
| WORKFLOW-STEPS.md: logging rule | ✅ 20/20 (git steps via shared helper) |
| WORKFLOW-STEPS.md: import boundary | ⚠️ 2 violations (common helpers) |
| Style guide: canvas node | ✅ Compliant |
| Style guide: dialogs/config panels | ⚠️ Partially applied |
| Tests | ✅ 148/148 pass — ⚠️ no router tests, no coverage tooling |
| Ruff | ⚠️ 531 findings, concentrated in ported modules |
| CLAUDE.md accuracy vs. code | ❌ Major drift (auth, schema, scripts, tech stack) |
