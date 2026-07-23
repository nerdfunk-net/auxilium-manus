# Backend & Workflow Steps Analysis (Grok)

**Date:** 2026-07-19  
**Author:** Cursor Grok 4.5  
**Scope:** `backend/` with deep focus on `backend/workflow_steps/`, measured against `CLAUDE.md`, `doc/WORKFLOW-STEPS.md`, and current code.  
**Related prior doc:** `doc/BACKEND-ANALYSIS.md` (2026-07-08) — several claims there are stale (step count, auth maturity); this document is the current assessment.

---

## 1. Executive summary

Workflow steps are **well implemented and largely CLAUDE.md / WORKFLOW-STEPS compliant**. All 22 step packages share a consistent contract (`execute(*, config, context, run, artifact_service, node_id) → list[StepOutcome]`), are registered in both `registry.yaml` and `STEP_REGISTRY`, and use shared helpers under `workflow_steps/common/` appropriately. The execution engine (`StepRunner` → capability guards → executor → persist) is clear and sound.

The broader backend follows the Model → Repository → Service → Router layering with real enforcement (`check_router_repositories.py`). The main gaps are:

| Area | Verdict |
|------|---------|
| Workflow step contract | Excellent (9.5/10) |
| Workflow execution engine | Excellent (9/10) |
| CLAUDE.md layered architecture | Good (8/10) — fat routers/services remain |
| Security | Mixed (6.5/10) — solid scaffolding, concrete secret/path/SSRF gaps |
| Step test coverage | Good but incomplete (7/10) — 6 executors untested |
| File size / monolith risk | Moderate — services/git + nautobot update paths are the worst offenders |

**Bottom line:** Steps are not the weak point. Treat secrets-in-context, path sanitization holes outside `sanitize_relative_path`, and a few fat service/router modules as the priority follow-ups.

---

## 2. Workflow steps inventory

### 2.1 Packages (22)

| Step id (`registry.yaml`) | Package directory | Lines (`executor.py`) | Has `config.py` |
|---------------------------|-------------------|----------------------:|:---------------:|
| `get-nautobot-devices` | `get_nautobot_devices` | 148 | ✓ |
| `get-ise-devices` | `get_ise_devices` | 300 | ✓ |
| `get-ise-tacacs-key` | `get_ise_tacacs_key` | **436** | ✓ |
| `get-from-list` | `get_from_list` | 110 | ✓ |
| `get-git-devices` | `get_git_devices` | 106 | ✓ |
| `get-nautobot-attributes` | `get_nautobot_attributes` | 214 | ✓ |
| `update-nautobot-device` | `update_nautobot_device` | **381** | ✓ |
| `get-device-configs` | `get_device_configs` | 183 | ✓ |
| `run-command` | `run_command` | 245 | ✓ |
| `route-on-attribute` | `route_on_attribute` | 236 | ✓ |
| `update-attribute` | `update_attribute` | 188 | ✓ |
| `log-message` | `log_message` | ~90 | ✓ |
| `log-attributes` | `log_attributes` | 324 | ✓ |
| `fan-in` | `fan_in` | ~50 | ✓ |
| `merge-content` | `merge_content` | 261 | ✓ |
| `compare-data` | `compare_data` | **381** | ✓ |
| `filter-output` | `filter_output` | 286 | ✓ |
| `render-jinja-template` | `render_jinja_template` | 295 | ✓ |
| `store-artifact` | `store_artifact` | 340 | ✓ |
| `git-clone` | `git_clone` | thin wrapper | ✓ |
| `git-pull` | `git_pull` | thin wrapper | ✓ |
| `git-push` | `git_push` | thin wrapper | ✓ |

Shared code lives in `workflow_steps/common/` (~232 KB on disk): path/template helpers, credential resolution, content resolution, git helpers, ISE lookup, Nautobot resolve/update fields. That consolidation is a **strength**, not a monolith smell — executors stay focused.

### 2.2 Contract compliance checklist

| Requirement (CLAUDE.md / WORKFLOW-STEPS.md) | Status |
|---------------------------------------------|--------|
| One package per step under `workflow_steps/{step_id}/` | ✓ |
| `__init__.py` + `executor.py` (+ optional `config.py`) | ✓ all have config |
| Keyword-only `async def execute(...)` exact signature | ✓ all 22 |
| Raise `ValueError` (config) / `RuntimeError` (execution) | ✓ generally followed |
| Start/finish `logger.info` with kebab-case step id | ✓ (git trio via `git_workflow_step.py`) |
| Entry in `registry.yaml` | ✓ 22 |
| Dispatch-only entry in `step_registry.py` | ✓ no business logic |
| External code must not import step packages; only StepRunner calls executors | ⚠ two non-test violations (see §4.3) |
| Capability `requires` / `produces` / outcomes declared | ✓ |
| Fan-out notes on shared sinks (git/filesystem) | ✓ documented in registry |

**Verdict:** Steps are implemented to the documented standard. Registry ↔ dispatch table are in sync (no orphans).

---

## 3. Execution architecture (positive)

```
Hatchet workflow_run
  → StepRunner.execute_all / execute_one / execute_subgraph / resume_after_join
       → assemble input context from parent edge outcomes
       → STEP_REGISTRY[step_type]
       → pre_step_guard (capabilities from registry)
       → executor.execute(...)
       → post_step_guard (produces)
       → persist WorkflowStepResult
```

Notable strengths:

1. **`step_registry.py` is a pure dispatch table** — imports + dict only.
2. **Capability guards** (`services/workflow_context/guards.py`) enforce registry contracts at runtime, not only on the canvas.
3. **Bulky content uses `ArtifactRef`** — CLI/config blobs stay off the workflow envelope.
4. **Credentials are vault references** (`credential_reference` name) decrypted at use via `resolve_ssh_credential` — passwords are not stored in step config.
5. **Workflow Jinja uses `SandboxedEnvironment`** (`workflow_steps/common/jinja_render.py`).
6. **Path sanitization helper** `sanitize_relative_path` rejects `..` and is used by git sink, compare-data, log-attributes, store-artifact filename templates.
7. **Fan-out / fan-in** are first-class (`FanOutSignal`, join resume) with registry warnings for unsafe concurrent git/filesystem sinks.

---

## 4. CLAUDE.md standards — broader backend

### 4.1 Layering (Model → Repository → Service → Router)

| Check | Result |
|-------|--------|
| Routers importing repositories | **None** (enforced by `scripts/check_router_repositories.py`) |
| SQLAlchemy models in `core/models/` | ✓ |
| Pydantic in `models/` | ✓ |
| Services own business logic | Mostly ✓ |
| Thin routers | Mostly ✓; exceptions below |

**Fat / boundary-stretching routers:**

| File | Lines | Issue |
|------|------:|-------|
| `routers/sources/ise/ops.py` | 537 | Credential resolve + response shaping in router |
| `routers/sources/nautobot/ops.py` | 374 | Inventory resolve / preview orchestration |
| `routers/git/operations.py` | ~223 | Inline aggregation; soft-error bodies with `str(e)` |
| `routers/netmiko.py` | ~123 | Decrypt + Netmiko invoke in router |
| `routers/workflow_update_attribute.py` | ~103 | Calls `workflow_steps.common` directly (no service) |

### 4.2 External imports of `workflow_steps` (policy tension)

CLAUDE.md: *“External code must never import workflow_steps packages directly; only StepRunner calls executors.”*

Non-test violators:

| File | Import |
|------|--------|
| `routers/workflow_update_attribute.py` | `attribute_path`, `attribute_regex` (probe API) |
| `services/artifacts/sinks/git_sink.py` | `sanitize_relative_path` |

These import **common helpers**, not executors — pragmatic, but they break the letter of the rule. Prefer moving shared path/regex helpers to e.g. `services/workflow_context/` or `utils/` if the boundary must stay clean.

### 4.3 Regression guards (keep these)

Present and valuable:

- `scripts/check_router_repositories.py`
- `scripts/check_http_500_leaks.py`
- `scripts/check_text_sql.py`
- `scripts/check_asyncio_run.py`
- `core/safe_http_errors.raise_internal_server_error`

---

## 5. Security analysis

Severity scale: **High** (exploitable or secret exposure), **Medium** (needs auth + misconfig / privilege), **Low** (defense-in-depth / product-inherent).

### 5.1 High

#### H1 — TACACS shared secrets persist in workflow context

`get-ise-tacacs-key` writes `tacacs.shared_secret` into `DeviceContext.attribute_bags` and returns it in `StepOutcome` context. That envelope is persisted with step results / run output.

Anyone with `workflow_runs:read` (or equivalent) can read TACACS keys. `log-attributes` dumps the full context (`context.model_dump`), and `log-message` registry examples even interpolate `{tacacs.shared_secret}`.

**Also:** `device_builders.py` can copy ISE shared secrets into device bags when building from ISE inventory.

**Recommendations:**

- Redact or encrypt secrets at rest in step results (store a vault ref or one-way handle, not the cleartext).
- Exclude `tacacs.shared_secret` (and similar) from `log-attributes` / API run payloads by default.
- Audit logs so secrets are never written at `INFO`.

#### H2 — Unsandboxed Jinja in TemplatesService

Workflow rendering correctly uses `SandboxedEnvironment`. The template library preview/render path does not:

```169:169:backend/services/templates/templates_service.py
            rendered = JinjaTemplate(template_content).render(**variables)
```

Privileged template authors could use unrestricted Jinja constructs. Align with the sandboxed env used by workflow steps.

### 5.2 Medium

#### M1 — Git `repo_path` allows `..` segments

```31:32:backend/services/git/paths.py
    sub_path = (repository.get("path") or repository["name"]).lstrip("/")
    return PROJECT_ROOT / "data" / "git" / sub_path
```

No rejection of `..`. A malicious repository `path`/`name` can escape `data/git/`.

#### M2 — Filesystem sink `output_subdirectory` not fully sanitized

`FilesystemArtifactSink` strips leading `/` `\` from `output_subdirectory` but does **not** reject `..`. Per-file relative paths *are* checked (`".." in normalized.parts`). Harden the subdirectory the same way as `sanitize_relative_path`.

#### M3 — SSRF via configurable source URLs

ISE and Nautobot base URLs come from admin-configured sources and are passed to HTTP clients with no private-IP / scheme allowlist. Mitigated by auth + source-admin permissions; still no DNS-rebinding / link-local controls. ISE also allows `verify_ssl=False`.

#### M4 — Exception text in soft-error / non-standard 500 paths

- `routers/git/operations.py` returns `str(e)` in JSON `"message"` on failures (not always via `raise_internal_server_error`).
- Some git/nautobot CRUD paths still raise hard-coded HTTP 500 without `error_id` correlation.
- Client-facing 400/404 with `detail=str(exc)` is generally acceptable for validation.

#### M5 — Full tracebacks stored on failed step results

`step_runner.py` persists `traceback.format_exc()[:4000]` into `error_message`. Privileged operators see paths and internal frames. Prefer a sanitized message + log correlation id; keep full traceback only in worker logs.

### 5.3 Low

#### L1 — Remote CLI as a feature (`run-command` / Netmiko)

No host `subprocess` / `shell=True` injection path found. Risk is intentional: authorized users send arbitrary device CLI. Acceptable for a NetDevOps product; document and gate with permissions.

#### L2 — User-controlled regex (ReDoS)

`update-attribute` / `filter-output` compile user regexes. A pathological pattern can hang a worker. Consider timeouts or size limits on pattern/input.

#### L3 — In-memory login rate limit

Auth rate limiting is per-process; weaker under multiple workers.

### 5.4 Security positives (keep)

- Sandboxed Jinja for workflow templates
- `sanitize_relative_path` for export/compare paths
- Credential vault + decrypt-at-use for SSH
- Capability-gated step execution
- Permission-gated routers (`require_permission`)
- AST checkers for 500 leaks, raw SQL, router→repo bypass
- Artifact content off the JSON envelope

---

## 6. Large files and monolithic blocks

### 6.1 Backend top files (excluding tests)

| Lines | Path | Assessment |
|------:|------|------------|
| 745 | `services/git/service.py` | **Monolith candidate** — facade covering path/clone/sync/files |
| 736 | `services/git/file_service.py` | Broad file R/W/search surface |
| 704 | `services/nautobot/devices/interface_workflow.py` | Large but domain-scoped workflow |
| 650 | `services/nautobot/devices/update.py` | Large orchestration |
| 626 | `services/git/debug_service.py` | Debug diagnostics bulk |
| 605 | `services/execution/step_runner.py` | Appropriately large engine |
| 537 | `routers/sources/ise/ops.py` | **Fat router** — should thin |
| 504 | `services/nautobot/resolvers/device_resolver.py` | Large resolver |
| 495 | `services/sources/nautobot/live_query_mixin.py` | Mixin weight |
| 489 | `services/nautobot/managers/vm_manager.py` | Manager size |
| 477 | `hatchet/workflows/workflow_run.py` | Orchestration (OK) |
| 471 | `services/nautobot/devices/common.py` | Facade (documented pattern) |
| 436 | `workflow_steps/get_ise_tacacs_key/executor.py` | Largest step — multi-tier lookup |
| 381 | `workflow_steps/update_nautobot_device/executor.py` | Complex step |
| 381 | `workflow_steps/compare_data/executor.py` | Complex step |

Backend total (rough): **~368 Python files, ~44k lines**.

### 6.2 Workflow-step size assessment

Within `workflow_steps/`, sizes are **reasonable**. The heaviest executors encode real domain logic (ISE TACACS priority tiers, Nautobot updates, compare/normalize). Shared helpers already absorb cross-cutting concerns.

**Split candidates (optional, not urgent):**

1. `get_ise_tacacs_key/executor.py` — extract tier strategies (`name_exact_32`, `ip_prefix_scan`, …) into a `tiers.py` module.
2. `compare_data/executor.py` — already has `reference_reader.py`; could extract normalize/diff helpers.
3. `update_nautobot_device/executor.py` — interface sync vs field update could split further.

**Not a problem:** thin git-clone/pull/push wrappers over `git_workflow_step.py`.

### 6.3 Monolith risk outside steps

Highest maintenance risk is **`services/git/*`** (multiple 600–745 line modules) and **fat source routers**. Nautobot’s resolver/manager/facade split is the right pattern even when individual files are large.

---

## 7. Test coverage (workflow steps)

| Covered (dedicated or strong related tests) | Missing executor tests |
|---------------------------------------------|------------------------|
| compare_data, fan_in, get_device_configs, get_from_list, get_ise_devices, get_ise_tacacs_key, git_*, render_jinja_template, route_on_attribute, run_command, log_attributes, store_artifact, update_attribute, log_message | **filter_output**, **get_git_devices**, **get_nautobot_attributes**, **get_nautobot_devices**, **merge_content**, **update_nautobot_device** |

Common modules are well tested (`test_attribute_path.py`, `test_jinja_render.py`, `test_device_template.py`, `test_content_resolver.py`, `test_ise_lookup.py`, etc.).

**Priority test gaps:** inventory selectors (`get_nautobot_devices`, `get_git_devices`) and mutating `update_nautobot_device`.

---

## 8. Step quality notes (per category)

### Inventory selectors
Clean builders (`device_builders.py`), fan-out config supported, clear failure outcomes. Nautobot/git selectors need more unit tests.

### Device execution (`run-command`, `get-device-configs`)
Credential resolution is correct; content goes to artifacts; per-device success/failure modeling is solid.

### Control flow (`route-on-attribute`, `update-attribute`, `fan-in`, `filter-output`, `merge-content`)
Attribute path resolution is shared and tested. Route matching (case sensitivity, default outcome) is intentional and covered.

### Integrations (ISE / Nautobot)
ISE TACACS multi-tier lookup is sophisticated and well-commented; also the main secret-handling risk. Nautobot update path reuses resolve + expression helpers.

### Persistence (`store-artifact`, git-*)
Fan-out races are documented. Path sanitization is good for filenames; subdirectory hardening is incomplete (M2).

### Debug (`log-attributes`, `log-message`)
Useful for operators; dangerous when bags contain secrets (H1).

---

## 9. Scores

| Area | Score | Notes |
|------|------:|-------|
| Step package contract | 9.5/10 | All 22 compliant; 2 external common imports |
| Execution engine | 9/10 | Guards, fan-out, artifacts, error containment |
| CLAUDE.md layering | 8/10 | No repo bypass; fat routers/services |
| Security | 6.5/10 | Secrets in context + path/SSRF/Jinja gaps |
| Step tests | 7/10 | 16/22 executors covered |
| File hygiene | 7/10 | Steps OK; git/nautobot services large |

**Overall backend health (workflow-centric): solid / production-capable, with security hardening recommended before treating secrets as first-class workflow data.**

---

## 10. Recommended actions (prioritized)

### P0 — Security

1. Redact or vault-reference TACACS (and similar) secrets in persisted workflow context / run APIs.
2. Switch `TemplatesService.render` to `SandboxedEnvironment`.
3. Harden `repo_path()` and `output_subdirectory` against `..` / absolute escapes.

### P1 — Architecture hygiene

4. Move probe helpers out of `workflow_steps.common` (or relax/document the import rule).
5. Thin `routers/sources/ise/ops.py` and git status error responses (use safe 5xx helper).
6. Sanitize step-failure messages stored in DB (keep traces in logs only).

### P2 — Maintainability & tests

7. Add executor tests for the 6 missing steps.
8. Optionally split `get_ise_tacacs_key` tiers and reduce `services/git/service.py` / `file_service.py`.
9. Consider ReDoS limits on user regex in filter/update-attribute.

---

## 11. Conclusion

The workflow step subsystem is one of the **best-structured areas** of this backend: consistent packages, registry discipline, shared commons, sandboxed workflow Jinja, artifact offloading, and capability guards. CLAUDE.md’s step-adding checklist is being followed in practice.

Do not confuse “steps look good” with “backend security is closed.” The highest-impact issues today are **secrets riding in workflow context**, **unsandboxed template-library Jinja**, and **path construction gaps** outside the shared sanitizer. Address those before growing more steps that handle credentials or write to shared filesystems.
