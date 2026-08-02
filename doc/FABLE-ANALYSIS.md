# Backend Analysis — Fable Review

**Date:** 2026-08-02
**Scope:** `backend/` (~61,500 lines of Python), with emphasis on `workflow_steps/`, the execution engine, and conformance to `CLAUDE.md`.
**Method:** All four regression guards executed, `ruff check` (clean), full test suite (`641 passed in 6.3s`), coverage run (`--cov`), AST-based scans for dead modules and oversized functions, and manual review of the auth stack, execution engine, artifact storage, git/Nautobot/ISE service layers, and every workflow-step package.

---

## 1. Executive Summary

The backend is in **good architectural shape**. The layering rules from `CLAUDE.md` (Model → Repository → Service → Router), the workflow-step plugin contract, the secret-sealing design, and the safe-5xx-error policy are all followed with unusual consistency, and the four regression-guard scripts all pass. The workflow-step subsystem in particular is well-factored and well-tested.

The fussy findings cluster in five areas:

| Area | Verdict |
|---|---|
| CLAUDE.md architectural conformance | **Good**, with 4 concrete violations (§3) |
| Security | **Solid foundation**, 1 high finding (unbounded token refresh), several medium/low (§4) |
| Python best practices | **Good**, but deprecated APIs (`asyncio.get_event_loop`, `datetime.utcnow`) and 77 functions over 80 lines (§5) |
| Dead code | ~1,000+ lines of confirmed-dead Nautobot manager/resolver code (§6) |
| Testing | 641 green unit tests, but **53% coverage vs. the 80% target** and an **empty integration-test suite** (§7) |

No God Objects were found. One file (`step_runner.py`, 813 lines) marginally exceeds the 800-line limit.

---

## 2. What Is Done Well (verified, not assumed)

- **Regression guards all green:** `check_asyncio_run.py`, `check_http_500_leaks.py`, `check_router_repositories.py`, `check_text_sql.py` — no `asyncio.run()` in routers, no leaky 5xx details in routers, no repository imports in routers, no forbidden `text()` SQL.
- **Ruff clean, zero f-string logging** anywhere in non-test code — the `%s`-style lazy-logging rule is followed universally.
- **Step contract compliance:** all 35 executable steps implement `async def execute(*, config, context, run, artifact_service, node_id, device_sessions)`; all 35 accept `device_sessions`; `step_registry.py` is a pure dispatch table (99 lines, no business logic) exactly as mandated. `registry.yaml` (37 entries) = 35 executors + `label` + `background` (correctly non-executable canvas decorations, filtered by `StepRunner._is_executable_node`).
- **Error classification** (`step_runner.py:59-76`): the `ValueError`/`RuntimeError` convention is enforced centrally, unexpected exceptions are withheld from users and replaced with an `error_id` correlated to worker logs — textbook implementation of the CLAUDE.md security rule.
- **Secrets design** (`services/workflow_context/secret_fields.py`): sealed Fernet envelopes at rest in attribute bags, `***REDACTED***` in all persisted output via `redact_secrets_in_data`, cleartext only transiently in memory. `StepRunner._serialize_outcomes` redacts before every persist. This is genuinely well thought out.
- **Auth hygiene:** timing-attack-safe login (dummy hash comparison, `auth_service.py:30-34`), Argon2 via `pwdlib.recommended()`, per-request DB-backed RBAC with user-override precedence, production guard refusing the default `SECRET_KEY` (`core/config.py:134-135`), warning on default admin password, login rate limiting (5/60s).
- **Jinja is sandboxed** in both render paths (`workflow_steps/common/jinja_render.py:13`, `services/templates/templates_service.py:29`) — SSTI is addressed.
- **Subprocess usage is safe:** every `subprocess.run` uses argument lists; no `shell=True`, no `eval`/`exec` anywhere in production code.
- **Immutability where it matters:** workflow contexts and device contexts are Pydantic models with `extra="forbid"`, mutated exclusively via `model_copy(update=...)` in `attribute_write.py`, `git_workflow_step.py`, etc.
- **Dependencies fully pinned:** all 19 entries in `requirements.txt` use `==`.
- **DB engine** uses `pool_pre_ping=True` (`core/database.py:19`).
- Auth coverage on routers is complete: every router either applies `require_permission` per route or at `APIRouter(dependencies=...)` level (verified per-file; the apparent gaps in `git/files.py`, `workflow_steps.py`, `sources/*/ops.py` are all covered by router-level dependencies).

---

## 3. CLAUDE.md / Architecture Violations

### 3.1 Services raise `HTTPException` — HTTP leaks into the worker (MEDIUM)

89 occurrences of `HTTPException` in `services/`. For request-scoped services this is a tolerated (if impure) FastAPI idiom, but it demonstrably leaks into the **non-HTTP execution path**:

- `workflow_steps/get_from_config/executor.py:9` imports `fastapi.HTTPException` inside a **workflow executor** running in the Hatchet worker, solely to catch what `SettingsService.get_source_config` raises (`executor.py:63-64`) and re-wrap it as `ValueError`.
- `services/settings/settings_service.py` raises `HTTPException` 11×, yet is consumed by worker-side step code.

This violates the spirit of "Thin routers that delegate to services" and the step-contract rule that steps deal in `ValueError`/`RuntimeError`. Services shared with the worker should raise domain exceptions; routers should translate them to HTTP.

### 3.2 Routers import `workflow_steps` packages (LOW–MEDIUM)

CLAUDE.md: *"External code must never import `workflow_steps` packages directly; only `StepRunner` calls executors."* Violations (all of `workflow_steps.common`, not executors, but the rule says *packages*):

- `routers/netmiko.py:29` → `workflow_steps.common.cisco_config_parsing`
- `routers/workflow_update_attribute.py:18-19` → `attribute_path`, `attribute_regex`
- `routers/sources/git/ops.py:31` → `cisco_config_parsing`

Either the rule should be amended to bless `workflow_steps/common/` as a shared library, or these helpers belong under `services/` (the cleaner fix — `workflow_steps/common/` currently plays two roles: step-internal helpers *and* de-facto shared library).

### 3.3 Module-level service singletons in routers bypass DI (LOW)

`dependencies.py` exists precisely to provide services, yet:

- `routers/git/files.py:24-25` — `_git_file_service = GitFileService()`, `_git_csv_service = GitCsvService()` at import time
- `routers/oidc.py:38-39` — `_config_service = OidcConfigService()`, `_oidc_service = OIDCService(...)`

Inconsistent with the rest of the codebase (e.g. `routers/git/debug.py` correctly uses `Depends(get_git_debug_service)`), and it makes these routers harder to test.

### 3.4 Inline construction + function-level imports in `RunService` (LOW)

`services/execution/run_service.py:193-202`: `get_run_artifact` imports `models.artifacts` and `services.artifacts` inside the method body and constructs `FilesystemArtifactService(settings.data_directory)` per call instead of receiving it. Same file is otherwise cleanly injected.

### 3.5 CLAUDE.md documentation drift (LOW, fix the doc)

- CLAUDE.md's Nautobot directory listing names `devices/import_service.py` — **the file does not exist**.
- Tech stack says **"Python 3.9+"**, but the code requires ≥3.12: PEP 695 generics (`class BaseRepository[T]`, `repositories/base.py:13`), `datetime.UTC`, and the venv is Python 3.14.
- The listing also omits `managers/vm_manager.py`, `managers/cluster_manager.py`, `resolvers/cluster_resolver.py`, `devices/query.py`, `devices/attribute_bag.py`, `devices/types.py` — stale relative to the tree.

---

## 4. Security Findings

### 4.1 HIGH — Unbounded token refresh: expiry is effectively decorative

`services/auth/auth_service.py:51-73` (`refresh_access_token`) decodes with `options={"verify_exp": False}` and **no limit on how long ago the token expired**. There is no separate refresh token, no `iat`-based maximum session age, and no revocation list. Consequences:

- A stolen/leaked access token — from a log, a backup, a compromised laptop — can be exchanged for a fresh 60-minute token **years later**, as long as the user row is still active.
- `ACCESS_TOKEN_EXPIRE_MINUTES` provides no real security boundary; it only bounds the window between keepalives.

Mitigations (pick one): enforce a maximum refresh window (e.g. reject tokens whose `exp` is older than N hours), add an `iat` claim plus absolute session lifetime, or move to proper refresh tokens with rotation. Positive note: refresh *does* re-check `is_active` and username match, so deactivation eventually cuts access.

### 4.2 MEDIUM — No cycle detection: cyclic graphs silently drop steps

`StepRunner._topological_sort` (`step_runner.py:787-813`) is Kahn's algorithm **without a cycle check**: nodes in a cycle never reach in-degree 0 and are silently omitted from the execution plan. Because `create_pending_step_results` only creates rows for ordered nodes, cycle members produce **no step results at all**, and `execute_all` can return `True` (run "completed") while part of the workflow never ran. CLAUDE.md explicitly claims *"The backend validates the graph"*; no cycle/graph validation exists anywhere in `services/workflow/workflow_service.py` (pure CRUD) or the run submission path. Even if React Flow prevents cycles in the UI, the API accepts arbitrary `canvas_nodes`/`canvas_edges`. Fix: after the sort, `if len(result) != len(node_map): raise ValueError("workflow graph contains a cycle")` — one line, and it belongs in definition validation too.

### 4.3 MEDIUM — `require_permission` never checks `user.is_active`

`core/auth.py:85-100` resolves permissions via `RBACService`, which contains **no `is_active` check** (verified: zero hits in `rbac_service.py`/`rbac_repository.py`). `get_current_user` does check it — but endpoints protected only by router-level `require_permission(...)` dependencies authorize a **deactivated user for up to `ACCESS_TOKEN_EXPIRE_MINUTES`** after deactivation, as long as their RBAC rows remain. Cheap fix: have `require_permission`'s checker load the user (or add an `is_active` join in `has_permission`).

### 4.4 LOW — Artifact ID interpolated into filesystem paths without validation

`FilesystemArtifactService._content_path` (`filesystem_artifact_service.py:31-35`) does `self._artifacts_dir / f"{artifact_id}.content"` where `artifact_id` arrives as a raw `str` path parameter (`routers/workflow_runs.py:91-105`). Traversal is *currently* impractical (path segments can't contain `/` through Starlette routing, and `get_for_run` requires a matching `run_id` in the meta file), but this is accidental safety, not designed safety. Artifact IDs are always `uuid4()` — validate the format at the router (`artifact_id: UUID`) or in the service.

### 4.5 LOW — Test-connection endpoints are server-side request primitives

`POST /sources/nautobot/test-connection` (`routers/sources/nautobot/ops.py:61`) and the ISE equivalent (`routers/sources/ise/ops.py:261`) accept an **arbitrary URL + token** and make the backend connect to it, gated only by the *read* permission of the respective source. Combined with response detail (`Connection failed: {exc}`), this is a modest SSRF/port-probing primitive against the backend's network position — which in this product is precisely the management network. Suggest gating these on `write` (they exist to configure sources) and normalizing error responses.

### 4.6 LOW — In-memory login rate limiting

`routers/auth.py:19-21` — `login_attempts` is a per-process dict. Under multiple uvicorn workers or a restart, limits reset/multiply; Redis is already a dependency and would make this real. Also, keys for failed attempts are never pruned except on success (`login_attempts.pop` at line 44), so the dict grows slowly without bound.

### 4.7 Informational

- `verify_ssl=False` is supported as a persistent no-verify `httpx.AsyncClient` in both Nautobot (`services/nautobot/client.py:36`) and ISE (`services/ise/client.py:36`) clients. Defensible for lab gear with self-signed certs, and it is at least logged per request — but there is no UI/scope guard preventing it in production configurations.
- Netmiko (`services/network/netmiko/connection.py`) performs no SSH host-key verification (Netmiko default auto-accepts). Standard for NetDevOps tooling, but worth stating in the security docs.
- Git operations embed credentials in the remote URL passed to `git` argv (`services/sources/git/git_source_service.py:85-95`); argv is visible via `ps` on shared hosts. Output redaction (`_redact_secrets`) is present and correct; consider `GIT_ASKPASS`/credential-helper injection instead.
- `services/git/debug_service.py` `test_write`/`test_delete`/`test_push` perform real writes and pushes against configured repositories. Properly gated behind `git.debug:execute` — keep it that way, and consider whether these belong in production builds at all.

---

## 5. Python Best Practices

### 5.1 Deprecated APIs (should be fixed before they break on an upgrade)

- **`asyncio.get_event_loop()` inside running coroutines** — deprecated since 3.10, warns/misbehaves on 3.12+; 8 occurrences: `routers/sources/git/ops.py:86,131,172,231,253`, `workflow_steps/set_default_attributes/executor.py:108`, `workflow_steps/get_git_devices/executor.py:67`, `workflow_steps/get_from_config/executor.py:68`. Replace with `asyncio.get_running_loop()` or, better, `asyncio.to_thread(...)` (already used correctly in `filesystem_artifact_service.py:66`).
- **`datetime.utcnow()`** — deprecated in 3.12: `routers/sources/nautobot/crud.py:168` (also hand-appends `"Z"`). Use `datetime.now(UTC)` as the rest of the codebase does.
- **Naive `datetime.now()`** in `services/git/debug_service.py:90,298,318` — inconsistent with the codebase's otherwise-strict `datetime.now(UTC)` convention.

### 5.2 Function length (rule: <50 lines; 77 functions exceed 80)

The executor entry points are the systematic offenders — `execute()` monoliths that inline config parsing, per-device iteration, outcome assembly, and summary building:

| Lines | Location |
|---|---|
| 288 | `workflow_steps/deploy_rendered_template/executor.py:84` `execute` |
| 245 | `workflow_steps/update_nautobot_device/executor.py:83` `execute` |
| 243 | `services/git/debug_service.py:242` `test_push` |
| 240 | `services/nautobot/devices/update.py:49` `update_device` |
| 238 | `workflow_steps/add_to_ise/executor.py:122` `execute` |
| 219 | `workflow_steps/compare_data/executor.py:164` `execute` |
| 216 | `services/nautobot/managers/ip_manager.py:43` `ensure_ip_address_exists` |
| 202 | `workflow_steps/run_command/executor.py:78` `execute` |
| 197 | `workflow_steps/add_to_nautobot/executor.py:109` `execute` |
| 196 | `hatchet/workflows/workflow_run.py:399` `_dispatch_children` |

Contrast with `get_ise_tacacs_key/executor.py`, which decomposes its 439 lines into small `_tier_*` helpers — that is the pattern the big executors should follow (extract `_parse_config`, `_run_for_device`, `_build_outcomes`).

### 5.3 File size (rule: ≤800 lines)

Only one violation: `services/execution/step_runner.py` — **813 lines**. Marginal, and the file is cohesive and superbly documented; extracting the graph utilities (`_topological_sort`, `_downstream_node_ids`, `_find_join_node_id`, `_child_node_ids`, ~130 lines of static methods) into `services/execution/graph.py` would fix both this and give cycle detection (§4.2) a natural home. Next-largest files (`git/service.py` 735, `hatchet/workflows/workflow_run.py` 705) are within the limit but trending up.

### 5.4 Minor

- `step_runner.py:806` — `queue.pop(0)` on a list is O(n²); `collections.deque` is already imported in the same file. Irrelevant at canvas scale, but sloppy next to otherwise careful code.
- `repositories/base.py` dual-mode sessions (own-session-with-commit vs. caller-session-with-flush) are correct but subtle; the behavioral difference (commit vs. flush) is only discoverable by reading the implementation. A docstring on `create()` would prevent misuse.
- Type hints are consistently present, including `TYPE_CHECKING`-guarded `DeviceSessionPool` imports in non-SSH executors, per the documented pattern. Good.

---

## 6. Dead Code

Confirmed dead (zero references outside their own definition/`__init__` re-export, and not covered by the CLAUDE.md facade path):

| Item | Size | Evidence |
|---|---|---|
| `services/nautobot/managers/vm_manager.py` (`VirtualMachineManager`) | 466 lines | No caller anywhere; not in `DeviceCommonService` facade imports (`devices/common.py:37-47`) |
| `services/nautobot/managers/cluster_manager.py` (`ClusterManager`) | ~130 lines | Same |
| `services/nautobot/resolvers/cluster_resolver.py` (`ClusterResolver`) | ~90 lines | Same |
| `services/nautobot/common/interface_types.py` (`normalize_interface_type`) | ~150 lines | Only re-exported from `common/__init__.py:17`; never called |
| `services/validation/` | empty dir | Contains only `__pycache__` — a leftover; delete the directory |

Coverage corroborates: `vm_manager.py` 10%, the others near zero. Per the user's task-completion rule, removal should include the `__init__.py` re-exports (`managers/__init__.py:8,13`, `resolvers/__init__.py:9,19`, `common/__init__.py:17`) and a final grep. **Not dead** (verified before flagging): `hatchet/worker.py` (entry point via `python -m hatchet.worker`), `routers/git/main.py` (imported by `routers/git/__init__.py`), and the remaining managers/resolvers (reached via the `DeviceCommonService` facade → `add_to_nautobot`/`update_nautobot_device` executors).

No God Objects found: `DeviceCommonService` is the sanctioned facade; `GitService` (735 lines) is large but single-purpose; nothing accumulates unrelated responsibilities.

---

## 7. Testing

- **641 unit tests, all passing, 6.3s** — fast, deterministic, well-named, with dedicated files per executor and per common helper. The step subsystem is genuinely well-tested (most executors 80–100% covered).
- **Total coverage: 53% vs. the 80% mandate.** The gap is concentrated in:
  - Git services: `debug_service.py` 0%, `operations.py` 0%, `cache.py` 0%, `file_service.py` 7%, `service.py` 21%
  - Nautobot write path: `devices/update.py` 7%, `devices/interface_workflow.py` 6%, `devices/creation.py` 14%, resolvers 7–9%
  - `services/cache/redis_cache_service.py` 11%
  - Routers for sources (`sources/ise/ops.py` 25%, `sources/nautobot/ops.py` 24%, `sources/nautobot/crud.py` 21%)
  - Under-tested executors: `update_nautobot_device` 15%, `merge_content` 16%, `filter_output` 14%
- **`tests/integration/` contains only a README — zero integration tests.** The testing rules require unit *and* integration *and* E2E coverage; the PostgreSQL-specific behavior the raw-SQL policy explicitly demands integration coverage for has none.
- The worst-covered code overlaps heavily with the highest-risk code (git write operations, Nautobot mutations) — the untested 47% is not the harmless half.

---

## 8. Prioritized Recommendations

1. **(Security, small)** Bound the refresh window in `refresh_access_token` — reject tokens expired more than N hours ago (§4.1).
2. **(Correctness, one line)** Raise on cycle in `_topological_sort`, and add graph validation to workflow save/run submission (§4.2).
3. **(Security, small)** Check `is_active` in the `require_permission` path (§4.3); validate `artifact_id` as UUID (§4.4).
4. **(Cleanup, mechanical)** Delete `vm_manager.py`, `cluster_manager.py`, `cluster_resolver.py`, `interface_types.py`, `services/validation/`, and their re-exports (§6).
5. **(Architecture, incremental)** Introduce domain exceptions for `SettingsService` (and any service the worker touches); drop the `fastapi` import from `get_from_config` (§3.1). Move router-consumed `workflow_steps/common` helpers into `services/` (§3.2).
6. **(Modernization, mechanical)** Replace the 8 `get_event_loop()` call sites and the `utcnow()`/naive-`now()` stragglers (§5.1).
7. **(Testing, sustained)** Target the git write path and Nautobot mutation services first — highest risk, lowest coverage; stand up the integration suite against real PostgreSQL (§7).
8. **(Docs, trivial)** Fix CLAUDE.md drift: Python version, Nautobot file listing (§3.5).
9. **(Refactor, opportunistic)** Extract graph utilities from `step_runner.py`; decompose the five largest `execute()` functions following the `get_ise_tacacs_key` tier-helper pattern (§5.2, §5.3).
