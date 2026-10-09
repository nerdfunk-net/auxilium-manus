# Open Findings — merged FABLE backend analyses (2026-10-09)

Sources merged:

- `FABLE_BACKEND_20260902.md` (S1–S16, §4 Python notes, §6 refactoring)
- `FABLE_BACKEND_20260912.md` (V, T, R, W series, §9 repository hygiene)
- `FABLE_BACKEND_20260916.md` (SM, B series, docs drift)

Plans cross-checked: all seven you listed, plus `FABLE_20260912.md` and `FABLE_BACKEND_20260916.md`,
which carry the status of the 09-12 blockers and SM1–SM3/B1/B2.

**Method.** Every finding that was open in any analysis, or whose status was not stated, was
re-checked against the working tree on `main` (`4cc19a0`, clean) on 2026-10-09: grep/read of the
cited location, `ruff check .` (clean). `pyright 1.1.406` was run: **73 errors** (basic mode) — the "158 advisory errors" figure in the 09-12 analysis is stale. Integration tests and a live
OpenBao/Infisical/Batfish were not run. Nothing here was fixed — this is the review input for the plan.

**Impact rating (my own, to be overridden by you).** Judged for this app as deployed: a
single-tenant internal NetDevOps tool, admin-granted permissions, Docker deployment, repo about to go public.

| Rating | Meaning |
|---|---|
| **High** | Exploitable or data-losing in a realistic setup; fix before public release |
| **Medium** | Real weakness or correctness bug with a plausible trigger; fix in the next hardening pass |
| **Low** | Hardening, hygiene or edge case; fix opportunistically (often a 1–5 line change) |
| **None** | Accepted risk / by design / informational |

**Result:** nothing rates High. 14 Medium, 42 Low, 5 None (rows; bundled IDs count once). The Medium items are listed in §5.

---

## 1. Status changes since the analyses were written

Items the analyses list as open, or never marked, that the code now shows as **resolved**:

| ID | Was | Now |
|---|---|---|
| SM1–SM3, B1, B2 | no status column in the 09-16 analysis | Fixed per `FABLE_BACKEND_20260916.md`; code confirms: `healthy` check in `openbao_client.ensure_started`, `transport_policy.validate_outbound_http_url`, `secret_manager_auth` (generic only), `secret_manager.` in `PROTECTED_RESOURCES`, `fixed` mode rejected in `secret_set`, `validate_outbound_http_url` in `batfish/source_config_service.py`, `sources.batfish:query` seeded and required on query routes |
| SM4 | open | Fixed (`b46bc5d`, `FABLE_BACKEND_20260916_SM4.md`) |
| V7 (login storm on 403) | open | **Mostly mitigated** by V4: one re-login + one retry, a second 403 keeps the token (`services/vault/client.py::_request`). Residual: a policy-denied path still costs one extra login per call → folded into V7 below, rated Low |
| SM11 (untested adapters/registry/router) | open | **Mostly done**: `test_secret_manager_{openbao_client,infisical_client,registry,router,policy,connection_service}.py` exist. Only `config.py` has no test file → residual below |
| SM9 (`name` max_length) | open | `name` has `max_length=255` on create. Rest of SM9 still open |
| T6 (doc promises OIDC admin-binding) | open | Doc claim no longer in `CLAUDE.md`/`doc/claude/auth.md`. The missing feature remains (see T6) |
| `get_current_user` / `_require_active_user_id` duplication (09-02 §6.4) | open | Fixed: both use `_load_active_user` |
| `workflow_steps/run_command/executor.py` 1 073 lines (09-12 §7) | open | Split into a package; **no backend file exceeds 800 lines** |
| `StepRunner` / `workflow_run.py` god objects (09-02 §6.1) | open | Split into packages |
| `scripts/ise_test*.py` with `print`/sandbox passwords (09-02 §6.5, 09-12 §9.18) | open | Gone from `backend/scripts/` |
| Batfish / Secret Manager entries in `doc/SECURITY-NOTES.md` (09-16 §3.3) | open | Present |
| `ruff` | 3 findings (09-02) | Clean |
| CI workflow (09-02 §3, 09-12 §7 "CI: ✅") | claimed present | **Gone** — deleted in `777c071`; see Q9 |
| §4.2 blocking work in `async def` handlers, §4.3 `os.environ` mutation, CI workflow | open | Fixed (`FABLE_20260902_REST.md`, S7) |

Items re-checked and **confirmed fixed** (no action): S1–S8, S10–S13, T1, R1, R2, V1–V4, SM1–SM4, B1, B2 (see the per-analysis status columns).

---

## 2. Open security and correctness findings

### 2.1 Authentication, sessions, RBAC

| ID | Impact | Finding (verified state) | Location | Fix | Effort |
|---|---|---|---|---|---|
| T2 ✅ fixed (Phase 1) | **Medium** | `PUT /users/{id}`: a `users:write` holder can change their **own** password or username without the current password. `assert_may_take_over` exempts self; `assert_not_self` is only used for roles/overrides. Enables the S14 inheritance path. | `services/users/user_service.py::update_user` | Call `assert_not_self` for password/username changes; self-service goes through `/auth/change-password`. | S |
| R3 ✅ fixed (Phase 1) | **Medium** | `set_active(user_id, True)` skips `may_touch_target`, so a non-admin `users:write` holder can reactivate a deactivated **admin** (P4 violation). The OIDC approval path (non-admin targets) is unaffected. | `services/users/user_service.py::set_active` | Call `may_touch_target` on the activate branch. | S |
| S14 / R6 | **Medium** | Inventories are owned by `created_by: str` (username). Renaming a user (or T2 self-rename) inherits a former user's private inventories. Still `created_by` + index on `scope, created_by`. | `core/models/inventories.py` | Add `owner_user_id` FK like `credentials`; keep the string for display. Needs a migration/back-fill. | M |
| T3 ⏸ deferred (Phase 1: ~390 router tests stub minimal tokens) | Low | Legacy-token tolerance still in `_load_active_user` (`isinstance` guards on `tv` and `sid_iat`). No such tokens exist in a fresh public deployment. | `core/auth.py` | Make `tv` and `sid_iat` mandatory; fix test doubles. | S |
| T4 ✅ fixed (Phase 1) | Low | `REFRESH_TOKEN_MAX_AGE_HOURS` (24) vs `SESSION_MAX_AGE_HOURS` (12): no cross-validation; the extra window is unreachable. | `core/config.py` | Validate `refresh <= session` or drop the setting. | S |
| T5 | Low | Logout bumps `token_version` → ends every session on every device; `jti` minted but unused. | `routers/auth.py::logout` | Document in UI copy, or add a Redis `jti` denylist. | S/M |
| T6 | Low | No endpoint writes `oidc_provider`/`oidc_subject` on an existing account; linking requires a DB edit. Safe (refusal path), just missing. | `models/rbac.py`, `routers/users.py` | Admin-only fields on `UserUpdate` or leave as documented limitation. | M |
| R4 ✅ fixed (Phase 1) | Low | `rbac.permissions:delete` can delete a seeded catalog permission; cascades remove it from every role incl. `admin` until next restart re-seeds. Admin-only foot-gun. | `routers/rbac/permissions.py` | 409 for permissions in `DEFAULT_PERMISSIONS`. | S |
| R5 ✅ fixed (Phase 1) | Low | `delete_role` on a custom role ignores P4 (strips it from admins too). Privilege reduction only. | `services/auth/rbac_service.py::delete_role` | Optional: require admin when any holder is admin. | S |
| R7 | Low | `has_permission` = 2 + 2N queries per check; the `User` row is still loaded by `get_current_user` and again by `require_permission` (R7 re-confirmed in code). Performance only. | `services/auth/rbac_service.py` | One `EXISTS` over `user_roles ⋈ role_permissions` after the override lookup. | M |
| R8 / S16 | None | Deny-override on non-protected permission needs no actor check (reduction only); `oidc/debug` is dev-tools + permission gated. By design. | — | — | — |
| S9 | **Medium** | Generic per-user rate limiting still absent. Limiters exist only for login, change-password and the git webhook (`grep` of `rate_limit`/`LoginRateLimiter`). Expensive endpoints open to any authenticated user: `netmiko/run-commands`, `sources/ise/*`, `sources/nautobot/*/analyze`, `git/*/sync`, `templates/render`, plus SM10 (`/secret-manager/connections/{id}/test` → live external login) and B3 (Batfish ad-hoc queries). | `main.py` / routers | Generic per-user Redis token-bucket dependency; reuse `LoginRateLimiter`. Resolves S9, SM10, B3 together. | M |

### 2.2 Vault (OpenBao)

| ID | Impact | Finding (verified state) | Location | Fix | Effort |
|---|---|---|---|---|---|
| V9 ✅ fixed (Phase 3) | **Medium** | `delete_credential` is **fail-open**: on `VaultError` it logs a warning and deletes the DB row, leaving the KV secret (and now no pointer to it). Contradicts the fail-closed design everywhere else. | `services/credentials/credentials_service.py::delete_credential` (l. 426–437) | Raise `CredentialVaultUnavailableError` (503) so the operator retries, or record orphaned paths for a sweep. | S |
| V12 ✅ fixed (Phase 3) | **Medium** | No vault readiness signal. `/health/ready` checks DB and Redis only; startup login is a soft-fail (ERROR log only); `OpenBaoService.healthy` exists but nothing reads it. A vault outage is silent until a step fails. | `main.py::health_ready`, `services/vault/client.py` | Add `vault_ok` to the ready response when `VAULT_ENABLED`. | S |
| V5 ✅ fixed (Phase 3) | Low | `start_vault_services()` always builds and logs in **both** the runtime and management clients, including in Hatchet workers that never write. Widens worker blast radius; management material is required for every worker deployment. | `core/vault.py::start_vault_services`, `hatchet/worker_services.py` | `with_management: bool`; API passes True, workers False; relax the guard accordingly. | S |
| V6 / SM7 ✅ fixed (Phase 3) | Low | Default dataclass `__repr__` on `VaultToken.client_token`, `VaultConfig.secret_id/token/client_key`, `SecretManagerConnectionConfig.auth_secret`, `_InfisicalToken.access_token`. No `repr=False` anywhere in `services/`. Exposure needs `%r`, a debugger or an error tracker capturing locals. | `services/vault/{auth,config}.py`, `services/secret_manager/{config,infisical_client}.py` | `field(repr=False)` on every secret field + one test. | S |
| V7 ✅ fixed (Phase 3) | Low | Residual of the 403 handling: a genuinely denied path still triggers one re-login per call (second 403 no longer invalidates). | `services/vault/client.py::_request` | Optional `lookup-self` check before invalidating. | S |
| V8 ✅ fixed (Phase 3) | Low | Management write/delete refreshes only its own cache; the runtime client in the same API process serves the old secret up to `VAULT_CACHE_TTL_SECONDS` (45 s). `credentials_service` never calls `invalidate` on the reader. | `credentials_service.py::_merge_vault_secret`, `delete_credential` | Passthrough `invalidate(path)` on `OpenBaoService`, call on the reader after write/delete. | S |
| V10 / SM6 ✅ fixed (Phase 3) | Low | No KV v2 check-and-set. `OpenBaoSecretManagerClient.set_field` reads through the 45 s cache, merges one key and writes the whole dict; concurrent writers across API/worker processes can drop a field. No `cas` anywhere in `services/vault/client.py`. | `services/vault/client.py::write_kv`, `services/secret_manager/openbao_client.py::set_field`, `credentials_service.py::update_credential` | `use_cache=False` on the read in `set_field`; send `options.cas`; map CAS 400 → retry/409. | M |
| V11 ✅ fixed (Phase 3) | Low | `CredentialCreate`: no `max_length` on `password`, `ssh_private_key`, `ssh_passphrase` (only name/username have one). | `models/credentials.py` | 64 KiB for keys, 1 KiB for passwords. | S |
| V13 ✅ fixed (Phase 3) | Low | `VAULT_SECRET_ID_FILE` permissions never checked (no `st_mode & 0o077` check). | `services/vault/config.py` | WARNING if group/other-readable. | S |
| V14 ✅ fixed (Phase 3) | Low | Runbook still recommends `secret_id_ttl=0` (lines 391, 396 of `doc/VAULT_INTEGRATION.md`); a leaked SecretID never expires. | `doc/VAULT_INTEGRATION.md` | Recommend `secret_id_ttl=2160h`, keep `num_uses=0`. | S |

### 2.3 Secret Manager (Infisical/OpenBao connections)

| ID | Impact | Finding (verified state) | Location | Fix | Effort |
|---|---|---|---|---|---|
| SM5 | **Medium** | Infisical `field` interpolated into `/api/v4/secrets/{field}` unsanitised: `../../v1/auth/x` is collapsed by httpx and steers the machine identity's bearer token to other Infisical API routes (bounded by the identity's own permissions). OpenBao path sanitiser (`_INVALID_SEGMENT_CHARS`) still lacks `#` and `%`, so `net/dev#x` addresses `net/dev`. No `A-Za-z0-9` validation exists in the steps. | `services/secret_manager/infisical_client.py`, `services/workflow_context/device_template.py` l. 13, `workflow_steps/secret_{get,set,generate}` | `^[A-Za-z0-9_.-]{1,255}$` for `field` in all three `_parse_config`s; validate the rendered path in `SecretManagerService`; add `#` `%` to the segment regex. | S |
| SM8 | **Medium** | Sync `httpx` called from async executors with no `to_thread` (`SecretManagerService.get_field/set_field`, once per device; only the Infisical login uses `to_thread`). Each call can stall a worker's event loop up to the 10 s timeout and serialise other steps. Registry lock still wraps DB + decrypt + login. | `services/secret_manager/service.py`, `registry.py` | `await asyncio.to_thread(...)` in the service; build the client outside the lock. | S |
| SM9 | Low | `SecretManagerConnectionRequest/UpdateRequest`: `backend_config` is a free `dict[str, Any]` (the "existing sub-models" in the 09-16 analysis do not exist; the service only checks required keys), `credential_name` has no `max_length` on update, no `extra="forbid"`. `secret-get` still ignores a non-int `version` (`isinstance(raw_version, int)`) and silently reads *latest* — a saved workflow with `"version": "3"` reads the wrong secret. | `models/secret_manager.py`, `workflow_steps/secret_get/executor.py::_parse_config` | Reject unknown / non-string keys in the service; coerce `version` with `int()` and raise `ValueError`. The `version` fix is a 2-line correctness fix. | S |
| SM10 | Low | `/secret-manager/connections/{id}/test` has no rate limit and triggers a live login per call; Infisical 401/403 handling treats both as "re-login". Part of S9. | `routers/secret_manager.py` | See S9. | — |
| SM11 | Low | `services/secret_manager/config.py` has no test file; router coverage not re-measured. | `tests/unit/` | Add `test_secret_manager_config.py`. | S |
| SM12 | None | Read-only vault boundary intact; per-workflow RBAC for write-capable steps deferred by design. | — | — | — |
| Infisical verb check | **Medium** | `PATCH`/`DELETE` shape and version history are documented as **unverified against a real Infisical instance** (`doc/SECRET_MANAGER_INTEGRATION.md` l. 329–347); `docker/infisical/` exists to close this and has not been run. Feature may fail on first real use. | `services/secret_manager/infisical_client.py` | Run the compose stack once, record behaviour, fix verbs. | M |

### 2.4 Batfish

| ID | Impact | Finding (verified state) | Location | Fix | Effort |
|---|---|---|---|---|---|
| B4 | **Medium** | `_get_session` holds the single `asyncio.Lock` across `to_thread(Session, …)` and `to_thread(set_network, …)` (blocking HTTP round trips): one slow coordinator serialises all Batfish calls in the process. `self._sessions` never evicted (one `Session` + question catalogue per network, i.e. per workflow). `list_networks`/`check_health` build throwaway sessions (no `load_questions=False` in the file). | `services/batfish/client.py` | Per-key locks / insert with `setdefault`; bounded LRU or idle TTL; `load_questions=False` on list-only paths. | M |
| B3 | Low | No result cap on ad-hoc queries (`routes` without filter serialises the fleet RIB; `extract-facts` with `/.*/`); no `truncated` flag; no rate limit. Now behind the `sources.batfish:query` permission. | `routers/sources/batfish/query.py`, `services/batfish/preview_service.py` | Row cap + `truncated`; part of S9. | M |
| B5 | Low | `network_name` override on `batfish-init-snapshot` lets a workflow author target another workflow's default network (`manus-workflow-<id>`) with `overwrite=True`. | `workflow_steps/batfish_init_snapshot/executor.py` l. 242 | Prefix overrides (`manus-named-…`); document shared networks. | S |
| B6 | Low | `device_id` used verbatim as filename (`configs_dir / f"{device_id}.cfg"`). No current source can produce `/`, but the invariant is unenforced. | `executor.py` l. 90 | `sanitize_path_segment(device_id)`. | S |
| B7 | Low | `validate-facts` runs `yaml.safe_load` inline on the event loop (l. 99, 177) for up to 20 000 files × 10 MiB. | `workflow_steps/batfish_validate_facts/executor.py` | Parse inside the `to_thread` call. | S |
| B8 | Low | Generic-question `params` are only None-filtered; pybatfish meta-kwargs (`question_name`, `exclusions`) can still be passed. | `services/batfish/query_helpers.py` ~l. 596 | Strip or reject. | S |
| B9 | None | `BatfishAPIError` embeds pybatfish exception text; routers sanitise to 502; run logs are access-scoped. | `services/batfish/client.py` | — | — |

### 2.5 Webhooks, git, secrets handling

| ID | Impact | Finding (verified state) | Location | Fix | Effort |
|---|---|---|---|---|---|
| W4 ✅ fixed (Phase 2) | **Medium** | `git_repo_lock` (moved to `services/git/repo_lock.py`, now used by every git-mutating step, store-artifact and parallel branches) is fail-soft **twice**: no Redis → proceed unlocked; 90 s acquire timeout → "proceeding anyway". Two writers on one working tree race on `index.lock` / pushes. The timeout branch is the surprising one and its blast radius grew with branch parallelism. | `services/git/repo_lock.py` | Raise `RuntimeError` on timeout; keep fail-soft only for "Redis unconfigured" (and log it loudly). | S |
| W1 ✅ fixed (Phase 2) | **Medium** | Webhook rate limit reuses the login limiter's budget (default 5/60 s per `repo:IP`): `limiter.check(f"webhook:{id}:{client_host}")`. A GitHub push storm or a CI burst gets 429, i.e. dropped change-request deliveries. The spoofing half of W1 was fixed with T1. | `services/change_requests/webhook_service.py` l. 86–90 | Own budget (e.g. 60/min per repo). | S |
| W6 | **Medium** | Secret redaction is shape-based. A step that copies an unwrapped secret into free text escapes it; with 52+ step packages this is the main residual leak into `WorkflowStepResult.output`. | `services/workflow_context/secret_fields.py` | Content pass: after resolving credential values, replace exact occurrences (≥ 8 chars) in persisted outputs. | M |
| W2 ✅ fixed (Phase 2) | Low | `webhook_secret` has no `min_length`. A 1-char HMAC key makes forgery trivial. | `models/git_repositories.py` l. 43 | `min_length=16`, on update too. | S |
| W3 ✅ fixed (Phase 2) | Low | `hmac.compare_digest` on `str` raises `TypeError` for non-ASCII input → unauthenticated 500 on a bad `X-Gitlab-Token` / `X-Hub-Signature-256`. | `core/webhook_signatures.py` | Compare `.encode("utf-8")` bytes. | S |
| W5 / S15 | Low | `CertificateService.upload` does `await file.read()` with no size cap; no global body limit (not documented in `docker/DOCKER.md`). Needs `system.certificates:write`. | `services/certificates/certificate_service.py` l. 65 | 64 KiB cap; document proxy limit. | S |
| W7 | None | Accepted risks (`verify_ssl=False` clients, Netmiko host-key off) still accurately documented. Stale references handled in §4. | `doc/SECURITY-NOTES.md` | — | — |

---

## 3. Open code-quality and refactoring findings

| ID | Impact | Finding (verified state) | Location | Fix | Effort |
|---|---|---|---|---|---|
| Q1 | Low | **86 functions over 80 lines** (was 43 on 09-02; the count doubled with the new step packages). Worst: `configure_replace_config::_process_one_device` 257, `undefined_and_unused::execute` 200, `compare_pyats_snapshot::_compare_one_device` 181, `git_workflow_step::run_git_workflow_step` 158, `open_change_request::execute` 154, `config_to_attributes::execute` 153, `batfish_validate_facts::execute` 153, `nautobot/devices/update::update_device` 149. **29 executors exceed 300 lines** (was 19). | `workflow_steps/*`, `services/nautobot/devices/update.py` | Per-phase functions; do the top ~8 when touching them. | L |
| Q2 | Low | `routers/sources/ise/ops.py` (553 lines, 30 repeated `except ISEAPIError/ISEValidationError` blocks) and `routers/sources/nautobot/ops.py` (486). Only `DomainError` has an exception handler in `main.py`. | those two routers | Register handlers for `ISEAPIError` (→ sanitised 502) and `ISEValidationError` (→ 400); delete ~250 lines. | M |
| Q3 | Low | `routers/sources/nautobot/crud.py::export_inventory` / `import_inventory` build/parse the document inline (thin-router violation). | `routers/sources/nautobot/crud.py` l. 151, 219 | Move to `InventoryService` / `inventory_transfer.py`. | M |
| Q4 | Low | **19 `except …: pass` sites** (was 13, then 18). Git helpers, redis cache, run_input_validation, run_command. | `services/git/*`, `services/cache/redis_cache_service.py`, … | `logger.debug` at least. | S |
| Q5 | Low | `service_factory.build_cache_service()` still swallows `Exception` and returns `None` with **no log**; callers silently run without cache (OIDC login 503, rate limiters fail-open/closed). | `service_factory.py` l. 206–217 | Log once. | S |
| Q6 | Low | Mass-assignment shape: `setattr(obj, key, value)` from `**kwargs` in 9 repositories (`user`, `rbac`, `credentials`, `inventory`, `schedule`, `templates`, `workflow`, `base`). Callers pass safe keys today. | `repositories/*` | Explicit parameters or an allow-list per repository. | M |
| Q7 | Low | `extra="forbid"` on only 4 of 44 model files; unknown fields silently dropped (`CredentialCreate`, `GitRepositoryRequest`, secret-manager requests, …). | `models/*` | Sweep request models. | M |
| Q8 | Low | `BaseRepository` used by only 3 repositories (git, secret-manager, base); 17 legacy `.query(` calls remain; optional-session pattern duplicates method bodies. | `repositories/base.py` | Adopt everywhere or delete. | M |
| Q9 | Low | `pyright` basic reports **73 errors** (largest: `services/git/repository_service.py` 11, `redis_cache_service.py` 8, `repositories/base.py` 6). **There is no CI at all right now**: `.github/workflows/backend-ci.yml` was deleted in `777c071`, although the 09-02/09-12 analyses and `CLAUDE.md` still describe it. 3 `noqa: E712` remain. | `core/models/git.py` (classic `Column`), `.github/`, `pyproject.toml` | Convert `GitRepository` to `Mapped`, re-baseline, decide whether to restore CI. | M |
| Q10 | Low | God-object candidates not addressed: `DeviceCommonService` (43 pass-throughs), `InterfaceManagerService`, `DeviceUpdateService.update_device`, `GitService.push`. | `services/nautobot/*`, `services/git/service.py` | Refactor on touch. | M |
| Q11 | None | Service file naming (`services/git/service.py` vs `{domain}_service.py`), no `ruff format --check` in CI. Cosmetic / deliberate. | — | — | — |

---

## 4. Open documentation and repository-hygiene findings

| ID | Impact | Finding (verified state) | Location | Fix | Effort |
|---|---|---|---|---|---|
| D1 | **Medium** | **No `SECURITY.md`** (`ls SECURITY.md` → missing). Needed before making the repo public. | repo root | Reporting channel, supported versions, accepted-risk paragraph from `SECURITY-NOTES.md`. | S |
| D2 | Low | `CLAUDE.md` l. 29: "15 tables (10 domain + 5 RBAC)". Code has 22 model files / 27 model classes. Key-file list lacks `secret_manager.py`, `background_tier`, `notifications`, `schedules`, `user_preferences`, `workflow_changes`, and the security entry points (`core/safe_urls.py`, `safe_hosts.py`, `oidc_redirect.py`, `dev_tools.py`, `vault.py`; only `production_guards` is mentioned, in `doc/claude/auth.md`). | `CLAUDE.md`, `doc/claude/database.md` | Update counts and lists. | S |
| D3 | Low | 10 dangling references to the deleted `doc/FABLE-ANALYSIS.md` (docstrings in `auth_service.py`, `settings/exceptions.py`, `settings_service.py`, `execution/graph.py`, `workflow_service.py`, 5 test modules, and `doc/SECURITY-NOTES.md` l. 3). | listed | Remove or repoint to `doc/analysis/`. | S |
| D4 | Low | `doc/SECURITY-NOTES.md` l. 42 still cites the old path `services/sources/git/git_source_service.py`. | `doc/SECURITY-NOTES.md` | Update path. | S |
| D5 | Low | `doc/BATFISH_INTEGRATION.md` l. 148–150 still says "exists on `feature/batfish`, not yet merged to `main`". The other drift items (RESOLVED bullet, SECURITY-NOTES entry) are fixed. | `doc/BATFISH_INTEGRATION.md` | Reword. | S |
| D6 | Low | `INSTALL.md` does not link `doc/VAULT_INTEGRATION.md`; `docker/DOCKER.md` does not document a request-body limit (see W5). | `INSTALL.md`, `docker/DOCKER.md` | Add both. | S |
| D7 | Low | Before flipping visibility: run `gitleaks`/`trufflehog` on the final tree; decide whether `routers/git/debug.py` (dev-tools gated) belongs in the public tree. | — | One-off. | S |

---

## 5. Suggested shortlist for the plan

These are the **Medium** items; everything else can ride along when the file is touched.

**Group A — one small hardening PR (all S, mostly 1–5 lines each, no migrations):**
T2, R3 (user-service guards) · W2, W3, W1 (webhook) · W4 (git lock timeout → fail) · V9, V12 (vault delete + readiness) · SM5, SM8, SM9-`version` (secret-manager steps) · D1 (`SECURITY.md`).

**Group B — needs design:**
S9 (generic per-user rate limiter; also closes SM10, B3) · S14/R6 (`owner_user_id` on inventories, with migration) · W6 (content-based redaction) · B4 (Batfish session cache) · Infisical verb verification (needs a running stack).

**Not worth planning now:** all Low refactoring (Q1–Q11) except Q2 and Q5 (cheap, real maintenance win), and the Low doc items beyond D1–D3.

## 6. Counts

| Area | Medium | Low | None |
|---|---|---|---|
| Auth / RBAC (incl. S9) | 4 | 7 | 1 |
| Vault | 2 | 8 | 0 |
| Secret Manager | 3 | 3 | 1 |
| Batfish | 1 | 5 | 1 |
| Webhooks / git / secrets | 3 | 3 | 1 |
| Refactoring / quality | 0 | 10 | 1 |
| Docs / hygiene | 1 | 6 | 0 |
| **Total** | **14** | **42** | **5** |

Rows that bundle several IDs (V6/SM7, V10/SM6, S14/R6, W5/S15) count once. The Medium rows are exactly the ones in §5.
