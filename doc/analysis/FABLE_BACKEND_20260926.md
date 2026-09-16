# Backend Analysis — 2026-09-26 (Secret Manager + Batfish)

Reviewer: Claude Fable 5.1
Reviewed on 2026-09-16 against `main` at `f0357f5`.
Scope: **only the code added since the previous audit** — the Secret Manager integration
(`doc/SECRET_MANAGER_INTEGRATION.md`, incl. `generate-password`) and the Batfish integration
(`doc/BATFISH_INTEGRATION.md`), backend side. Everything covered by
`doc/analysis/FABLE_BACKEND_20260912.md` (vault, tokens, RBAC, webhooks) is not re-audited here;
where a new finding is the same class as an old one, the old id is referenced (`V1`, `V6`, …).

Finding prefixes: `SM` (secret manager), `B` (batfish), `C` (compliance / docs).
Severity: **H** fix before publishing, **M** first hardening pass, **L** backlog.
"Publish" marks what I would not ship the feature without.

## 0. Verdict in one paragraph

Both features are well-structured and well-tested where the design put its attention: the
Batfish integration is genuinely careful (allow-listed generic questions, a "network must
already exist" guard against pybatfish's create-on-`set_network` behaviour, per-network session
caching, `to_thread` around every blocking call, sanitized 502s, escape-guarded git file
collection, 100 % test coverage on all eleven step executors), and the Secret Manager keeps the
promise that matters most — generated and fetched secrets are sealed before they touch the
attribute bag and never appear in metadata, summaries, or logs. The mechanical gates are green:
ruff clean on the 111 changed files, four guard scripts OK, 2 945 tests passing at 83.4 %,
pip-audit clean with the new pybatfish dependency tree.

What is missing is the **trust-boundary hardening that every other source in this codebase
already has**, and it is missing in the same way in both features. Neither the Batfish `host`
nor the Secret Manager `addr`/`site_url` goes through `core/safe_urls.validate_outbound_http_url`,
so a holder of the respective `:write` permission can point the backend at any host. For
Batfish that turns `init_snapshot` into a device-config exfiltration channel (**B1**); for the
Secret Manager it combines with `credential_name` resolving *any* global `ssh` credential into
"send that device password to my server" (**SM2**). Two more are functional rather than
security: the connection test endpoint always reports success (**SM1**), and Hatchet workers
never learn that a connection was edited, deactivated, or deleted (**SM4**). A literal secret
typed into `secret-set`'s `fixed_value` is persisted in plaintext in the workflow definition and
pushed to the workflows git repository (**SM3**), which contradicts the feature's own
"never persisted in plaintext" statement. Finally, the ad-hoc Batfish query endpoints let the
seeded read-only `viewer` role read routing tables and ACL verdicts of workflows that are
`private` to it (**B2**).

None of these is reachable without an authenticated user holding a permission that only an
admin can grant, which is why nothing here is rated H. I would fix SM1, SM2, SM3, B1 and B2
before calling either feature done.

---

## 1. What was run

| Check | Result |
|---|---|
| `ruff check` on the 111 changed non-test `.py` files | clean |
| `scripts/check_asyncio_run.py`, `check_http_500_leaks.py`, `check_router_repositories.py`, `check_text_sql.py` | all OK |
| `python -m pytest tests/unit` (full suite, ratchet 81 %) | 2 945 passed, 0 failed, coverage 83.44 %, 42 s |
| Feature subset (`-k "batfish or secret or generate_password or templates_batfish"`) | 392 tests, 3.5 s |
| `pyright` on changed files (venv interpreter) | 8 errors: 4 in `services/secret_manager/connection_service.py` (classic `Column` vs `Mapped` noise — the model uses `Column(...)` like `GitRepository`), 4 in pre-existing files outside scope |
| `pip-audit -r requirements.txt -r requirements-dev.txt` (now incl. pybatfish → pandas, requests, urllib3, …) | no known vulnerabilities (1 ignored, PYSEC-2026-2858) |
| grep on new code: f-string logging, `except …: pass`, `noqa: S*` | 0 / 0 / 0 |
| grep on new code: TLS verification opt-outs | 2 (`infisical_client.py`, `OpenBaoService._build_client` via a DB-configured `VaultConfig`) — see SM2 |
| `docker/batfish/docker-compose.yaml` | ports 9996/9997 bound to `127.0.0.1` only ✅ |
| `docker/infisical/` | only `docker-compose.yml` and a blank `.env.example` tracked; no secrets committed ✅ |
| Size | Secret Manager ≈ 2 100 lines, Batfish ≈ 5 400 lines backend; no file over 545 lines |

Coverage of the new modules by their own tests (`--cov-report=term-missing`, feature subset):

| Module | Cov | Module | Cov |
|---|---|---|---|
| `services/secret_manager/config.py` | **0 %** | `workflow_steps/secret_*/executor.py` | 84–88 % |
| `services/secret_manager/registry.py` | **0 %** | `workflow_steps/generate_password/executor.py` | 92 % |
| `services/secret_manager/openbao_client.py` | **0 %** | `workflow_steps/batfish_init_snapshot/{executor,git_source}.py` | 95 % / 90 % |
| `services/secret_manager/infisical_client.py` | **0 %** | `workflow_steps/batfish_validate_facts/executor.py` | 93 % |
| `routers/secret_manager.py` | **29 %** | other 9 `workflow_steps/batfish_*/executor.py` | 100 % |
| `services/secret_manager/service.py` | 52 % | `services/batfish/{query_helpers,preview_service}.py` | 98 % / 99 % |
| `services/secret_manager/connection_service.py` | 78 % | `services/batfish/client.py` | 75 % |
| `routers/sources/batfish/{crud,query,discovery,ops}.py` | 38 / 50 / 72 / 77 % | `services/batfish/*_spec.py`, `facts_specs.py` | 94–100 % |

The four 0 % modules are exactly where SM1, SM5, SM6 and SM7 live. The design doc already
flags this gap ("Known gap, not yet covered"); this audit confirms the gap contains real bugs.

---

## 2. Secret Manager integration

Files reviewed in full: `services/secret_manager/{service,config,registry,client,openbao_client,
infisical_client,connection_service,policy,exceptions}.py`, `core/models/secret_manager.py`,
`models/secret_manager.py`, `routers/secret_manager.py`,
`repositories/secret_manager/secret_manager_connection_repository.py`,
`workflow_steps/{secret_get,secret_set,secret_generate,generate_password}/*`,
the two additions to `services/vault/client.py` (`read_kv(version=)`, `metadata_kv`),
`services/workflow_context/device_template.py` (path rendering), `services/credentials/manager.py`
(`generic()`), `service_factory.py` / `main.py` / `hatchet/worker_services.py` wiring,
`services/auth/rbac_seed.py`, `workflow_steps/registry.yaml` entries, and the five test files.

### 2.1 What is done well

- **The pipe-only guarantee holds.** All four steps call `seal_secret(value)` before
  `set_device_attribute`, never write the value into `metadata` or `summary`, and
  `secret-generate` / `generate-password` `del value` immediately after sealing. The tests assert
  via a `json.dumps` scan that the generated value appears nowhere in the outcome. This reuses the
  existing envelope mechanism rather than inventing a second redaction path — the right call.
- **Generation is cryptographically sound.** `secrets.token_hex` / `secrets.choice` /
  `SystemRandom().shuffle`, bounded lengths (4–256 / 8–256), per-category minimums enforced at
  policy construction, frozen dataclasses. `PasswordPolicy` correctly rejects `total == 0` and
  `total > length`.
- **Layering is clean.** Model → repository → connection service → router; `SecretManagerService`
  is a facade that never imports a concrete adapter; backend dispatch lives only in the registry.
  The router is a thin delegate and maps `ValueError → 400`, everything else through
  `raise_internal_server_error`. The guard scripts pass.
- **OpenBao adapter reuses the hardened client** rather than re-implementing KV v2, so V3/V4
  (destroy-all-versions, lease-driven renewal, 403 re-login-once) apply automatically. The two
  additions to `OpenBaoService` are small and version-pinned reads correctly bypass the cache.
- **Fail-closed classification is right.** `SecretManagerError` → whole-step `failure` (all
  devices), a missing field → per-device `failure` (proceed with survivors), config problems →
  `ValueError`. Matches `get-ise-tacacs-key`'s established semantics.
- **Rendered KV paths are sanitized as a side effect of reusing `render_device_template`**:
  `sanitize_relative_path` rejects `..` segments and replaces `/ ? * < > : " | \` inside a
  segment, so a hostile device name cannot traverse out of the mount (verified with httpx's
  `MockTransport`: httpx *does* collapse `..`, so this sanitizer is load-bearing — see SM5 for the
  one character it misses).
- **`credential_name` is resolved global-only** (`CredentialManager.generic`, no
  `acting_user_id`), consistent with git auth.
- **Honest docs.** The Infisical version-history caveat, the unverified PATCH/DELETE verbs, and
  the missing tests are all stated plainly in the code and the doc.

### 2.2 Findings

| # | Sev | Finding | Location | Fix | Publish |
|---|---|---|---|---|---|
| SM1 | **M** | **`POST /secret-manager/connections/{id}/test` always reports success.** For OpenBao, `OpenBaoSecretManagerClient.ensure_started` awaits `OpenBaoService.startup()`, which *catches* `VaultError` on a failed AppRole login, logs it, sets `_healthy = False` and returns normally (the soft-fail that is correct for app boot is wrong for a connectivity test). For Infisical, `ensure_started` is a no-op and no request is made at all. So a wrong `secret_id`, a wrong `client_secret`, an unreachable `addr`/`site_url`, or a mistyped mount all return `{"success": true, "message": "Connected successfully"}`. The only thing the endpoint actually checks is that the DB row and its `credential_name` resolve. `_healthy` is set but never read (V12 again). | `routers/secret_manager.py::test_connection`, `services/secret_manager/{openbao_client,infisical_client}.py::ensure_started`, `services/vault/client.py::startup` | Make `ensure_started` prove authentication: for OpenBao, after `startup()` check `self._service._healthy` (expose it as a property) or issue `GET /v1/auth/token/lookup-self`, and raise `SecretManagerAuthError` if it fails; for Infisical, call `self._tokens.current(self._client)` (performs the login) inside `ensure_started`. Add router tests for the three failure classes. | yes |
| SM2 | **M** | **No outbound-URL policy, TLS opt-out honoured, and any global SSH credential can be used as the connection's auth material — together a credential-exfiltration path.** `_validate_backend_config` only checks that `addr` / `site_url` are non-empty. Nothing calls `validate_outbound_http_url` (which every other HTTP source does, blocking link-local/metadata targets and, unless allowed, loopback), nothing requires `https://`, and `verify_ssl=False` on the row is passed straight to `httpx.Client(verify=False)` / `VaultConfig(verify_ssl=False)` with no `environment != "development"` guard (the exact class of V1, which was fixed for `VAULT_VERIFY_SSL` two weeks ago). Meanwhile `load_connection_config` resolves `credential_name` through `CredentialManager.generic`, whose `_GENERIC_TYPES` accepts **`ssh` as well as `generic`** — i.e. any global network-device SSH credential. Combined: an actor with `secret_manager.connections:write` (only obtainable from an admin, but not a protected permission) creates a connection with `site_url = http://attacker:8080`, `credential_name = <the fleet's TACACS-fallback SSH credential>`, calls `/test` — and the Infisical adapter POSTs `clientId=<username>&clientSecret=<password>` to the attacker in cleartext. The OpenBao path does the same with `role_id`/`secret_id`. This bypasses `credentials:reveal` entirely. | `services/secret_manager/connection_service.py::_validate_backend_config`, `services/secret_manager/config.py::load_connection_config`, `services/secret_manager/{infisical_client,openbao_client}.py` constructors, `services/credentials/manager.py::_GENERIC_TYPES` | (1) Validate `addr` / `site_url` with `validate_outbound_http_url(url, resolve_dns=True)` on create/update *and* at client construction (config can be edited later). (2) Require `https://` and refuse `verify_ssl=False` outside `development`, mirroring `production_guards` for the vault. (3) Restrict the connection credential to a dedicated type — either `generic` only (drop `ssh` from what `load_connection_config` accepts) or, better, a new `secret_manager_auth` credential type so an SSH password can never be selected here. (4) Consider adding `secret_manager.connections` to `PROTECTED_RESOURCES` (P3): write on it is equivalent to reading credentials. Tests for each. | yes |
| SM3 | **M** | **`secret-set` `mode: fixed` stores a literal secret in plaintext in the workflow definition, and the definition is version-controlled into git.** `fixed_value` lives in the node config inside `workflows.canvas_nodes`, readable by every `workflows:read` holder of that workflow, and `WorkflowGitService._sync` writes `canvas_nodes` verbatim into the workflows `GitRepository` and pushes it. So a TACACS key or SNMP community typed into the panel ends up in a git history (and in every clone) in cleartext — while the *same* value is carefully sealed in the attribute bag one line later. No other step in the codebase stores a literal secret in config; every existing "fixed" mode (`credential_source: fixed` on `get-device-configs`, `deploy-rendered-template`, …) is a *credential reference*. The registry description and the doc say the value is "never persisted in plaintext". | `workflow_steps/secret_set/executor.py::_resolve_value`, `workflow_steps/secret_set/config.py`, `services/workflow/workflow_git_service.py::_workflow_to_git_payload` | Preferred: drop `fixed` mode; the supported ways to supply a value become `attribute` (run-input or an upstream `secret-get`/`generate-password`) and a credential reference (`credential_name` → `CredentialManager.generic`). If a literal must stay for lab use, gate it behind `settings.environment == "development"` and strip `fixed_value` in `_workflow_to_git_payload`. Update the registry description either way. | yes |
| SM4 | **M** | **Hatchet workers never see connection changes.** `SecretManagerClientRegistry` caches one client per connection id for the process lifetime; the router calls `registry.invalidate()` only in the **API** process. The two worker processes (where every step actually runs) keep the old client: an edited `addr`/`mount`/`project_id` is ignored, a rotated `credential_name` is ignored (OpenBao re-login will use the *old* SecretID after token expiry and then fail closed — safe but confusing), and, most importantly, `is_active = False` or a deleted row is checked **only** in `load_connection_config` on first use — deactivating or deleting a connection does not stop workers from using it until a restart. The Batfish doc's "remember to restart the Hatchet worker" note shows this is a known pattern for source *config*, but here it also disables the kill-switch. | `services/secret_manager/registry.py::get_or_create`, `routers/secret_manager.py` | Cheapest: in `get_or_create`, always read the row's `(is_active, updated_at)` (one indexed PK query) and rebuild/refuse when `updated_at` moved or `is_active` is false. Alternatively a short TTL (60 s) on cache entries. Long term: Redis pub/sub invalidation shared by the three processes (the doc already lists a Redis-backed cache as deferred). | |
| SM5 | L | **Infisical `field` is interpolated into the URL path unsanitized; OpenBao path misses `#`.** `f"/api/v4/secrets/{field}"` with `field = "../../v1/auth/x"` is sent as `/api/v1/auth/x` (httpx collapses dot segments; verified with `MockTransport`). A workflow author can therefore steer the machine identity's bearer token at other Infisical API routes (bounded by that identity's own permissions and by the fixed method/body). On the OpenBao side, `render_device_template` blocks `..`, `/`, `?` and friends but not `#`, so `network/dev#x/tacacs` reads/writes `network/dev` instead. | `services/secret_manager/infisical_client.py::{get_field,set_field,delete_field}`, `services/workflow_context/device_template.py::_INVALID_SEGMENT_CHARS` | Validate `field` against `^[A-Za-z0-9_.-]{1,255}$` in `_parse_config` of all three steps (Infisical secret keys are that anyway), and validate the *rendered* path against `^[A-Za-z0-9_./-]+$` with no `..` segment in `SecretManagerService` (one place, both backends). Add `#` and `%` to `_INVALID_SEGMENT_CHARS`. | |
| SM6 | L | **OpenBao `set_field` is read-modify-write through the 45 s TTL cache with no check-and-set.** `set_field` reads via `read_kv(path)` (served from `InProcessTTLCache` if fresh), merges one key, writes the whole dict. Within one process `write_kv` refreshes the cache so it is consistent; across the API process and the two workers, each with its own cache, two writes to *different fields of the same path* within 45 s can silently drop one. The doc calls the steps fan-out-safe "by construction" because the default template is per-device — true for the default, not for an operator-chosen path. V10 (no CAS) applies here too. | `services/secret_manager/openbao_client.py::set_field`, `services/vault/client.py::read_kv` | Give `read_kv` a `use_cache: bool = True` flag and pass `False` from `set_field`/`delete_field`; send `options.cas = <version from that read>` on the write and map the CAS 400 to a retry-once. | |
| SM7 | L | **Secrets in dataclass reprs (V6 recurs).** `SecretManagerConnectionConfig.auth_secret`, `_InfisicalToken.access_token`, and still `VaultConfig.secret_id`/`token`/`client_key` all have the default generated `__repr__`. `registry.get_or_create` logs nothing today, but `logger.warning(..., exc_info=True)` in `shutdown_all` and any future `%r` would print the AppRole SecretID / Infisical client secret. | `services/secret_manager/config.py`, `services/secret_manager/infisical_client.py`, `services/vault/config.py` | `field(repr=False)` on every secret-bearing field; one test asserting the secret is absent from `repr(cfg)`. | |
| SM8 | L | **Synchronous HTTP inside async executors, and a login inside the registry lock.** `SecretManagerService.get_field/set_field` call the adapters' sync `httpx` methods directly from the async executor (no `to_thread`), once per device; `InfisicalSecretManagerClient._request` may additionally perform a login. `registry.get_or_create` holds a process-wide `asyncio.Lock` while `load_connection_config` does DB + credential decryption. Each call can stall the worker's event loop for up to the 10 s timeout, serialising every other step on that worker. The doc acknowledges the sync style but not the loop-blocking consequence. `OpenBaoService` already shows the right pattern (`_run_blocking`). | `services/secret_manager/service.py`, `services/secret_manager/registry.py` | `await asyncio.to_thread(client.get_field, …)` etc. in `SecretManagerService`; build the client outside the lock (double-checked insert). | |
| SM9 | L | **Input bounds and strictness.** `SecretManagerConnectionRequest.name` has no `max_length` (DB column is 255 → an IntegrityError → sanitized 500 instead of 422); `backend_config: dict[str, Any]` is unbounded and unknown keys are stored verbatim; neither request model sets `extra="forbid"`. `secret-get` silently ignores a `version` that arrives as a string (`isinstance(raw_version, int)` only) and reads latest instead — the frontend sends a number today, but a saved/imported workflow with `"version": "3"` reads the wrong secret with no error. | `models/secret_manager.py`, `workflow_steps/secret_get/executor.py::_parse_config` | `max_length=255` on `name`, `max_length=64` on `credential_name`, validate `backend_config` through `OpenBaoConnectionConfig`/`InfisicalConnectionConfig` (they already exist but are never used); coerce `version` with `int()` and raise `ValueError` on failure. | |
| SM10 | L | **`/test` has no rate limit and triggers a live login to an external system per call**, and every 401/403 from Infisical — including a genuine policy denial — invalidates the token and re-logs-in (V7's shape). S9 (generic rate limiting) still open. | `routers/secret_manager.py::test_connection`, `services/secret_manager/infisical_client.py::_request` | Reuse `LoginRateLimiter` keyed `secret-manager-test:<user_id>`; distinguish 401 (re-login) from 403 (permission error, keep token). | |
| SM11 | L | **Untested adapters and router.** `config.py`, `registry.py`, `openbao_client.py`, `infisical_client.py` at 0 %, the router at 29 %. SM1 and SM5 would have been caught by a mocked-`httpx` test of each adapter and a `TestClient` test of `/test` with a failing login. | `tests/unit/` | Add `test_secret_manager_openbao_client.py`, `test_secret_manager_infisical_client.py` (MockTransport: login, 401 retry, create-vs-update, 404 → None, field with `/`), `test_secret_manager_registry.py` (lazy build, invalidate, unknown backend), `test_secret_manager_router.py` (CRUD 400/404, `/test` success **and** auth failure). | |
| SM12 | info | **The "structurally read-only" vault boundary is intact.** The write-capable `CredentialsService` client is still injected only by `routers/credentials.py`; the new domain is write-capable by design and uses its own AppRole. Per-workflow RBAC gating of write-capable steps remains deferred, as the doc states. Noting so the boundary is re-checked next time. | — | — | |

### 2.3 Design observations (no action required)

- `SecretManagerConnection` uses classic `Column(...)` declarations (like `GitRepository`) rather
  than `Mapped[...]` (like `Workflow`), which is the source of the 4 pyright errors in
  `connection_service.py`. Cosmetic, but the codebase now has two styles.
- `secret-get` applies the same `version` number to every device's path. Documented, but a
  "previous secret before rotation" workflow across many devices will rarely have aligned version
  numbers; a `version: -1` ("one before latest") semantic via `get_field_history` would be more
  useful.
- `render_device_template` raises `TemplateResolutionError` *outside* the per-device try block
  in all three steps, so one device with an unresolvable placeholder in strict mode fails the
  whole step rather than that device. Consistent with `store-artifact`; mention in the help panel.

---

## 3. Batfish integration

Files reviewed in full: `services/batfish/{client,query_helpers,preview_service,source_config_service,
credentials,facts_specs,ospf_facts,bgp_facts,node_properties_spec,interface_properties_spec}.py`,
`services/batfish/common/exceptions.py`, `routers/sources/batfish/{crud,ops,query,discovery}.py`,
`models/batfish.py`, all eleven `workflow_steps/batfish_*/executor.py`,
`workflow_steps/batfish_init_snapshot/git_source.py`,
`workflow_steps/common/batfish_{context,properties,combined_facts,ospf_facts,bgp_facts}.py`,
`core/safe_urls.py` (for comparison), the installed `pybatfish` 2026.8.19.3660 source
(`client/session.py`, `client/restv2helper.py`, `question/question.py`) for URL construction,
timeouts, retry policy and kwarg validation.

### 3.1 What is done well

- **The one dangerous dispatch is fenced.** `BatfishService._answer` does `getattr(session.q,
  name)` with no validation; the only caller that takes a name from request input,
  `query_generic`, checks a hard-coded `frozenset` first and the fifteen entries were verified
  against a live coordinator. Every typed question is a fixed string. pybatfish itself rejects
  unknown kwargs (`question.py` computes `var_difference`), so `params` cannot smuggle extra
  behaviour past the coordinator's own schema.
- **The create-on-`set_network` trap is closed everywhere it matters.** `assert_batfish_network_exists`
  runs before `resolve_latest_snapshot_name` *and* before an explicit-snapshot query in both
  resolution points, and the discovery router returns an empty list for an unknown network
  without touching `_get_session`. Regression tests exist for all three.
- **Concurrency reasoning is sound.** Sessions cached per `(host, port, network)`, `set_network`
  called exactly once per entry, `snapshot=` passed explicitly on every question, every pybatfish
  call in `asyncio.to_thread`. pybatfish's `Session` default `timeout=30` applies (verified), so
  a hung coordinator cannot block a worker forever (see B4 for the lock).
- **Errors are mapped correctly at both boundaries.** Routers: `ValueError`/`BatfishValidationError`
  → 400, `BatfishAPIError` → sanitized 502 via `raise_internal_server_error(status_code=…)`,
  everything else → sanitized 500. Steps: the non-table `Answer` case is turned into
  `BatfishAnswerFailedError` and re-raised as a `ValueError` naming the offending node, so users
  get a `configuration` category instead of "Unexpected error".
- **Git-sourced snapshots are collected safely.** `git_source.py` resolves `base_path` with
  `resolve()` + `relative_to()`, rejects symlinks escaping the repo, skips `.git/`, caps count and
  size, and fails loudly on zero or too many matches. Files are copied with index-prefixed
  cosmetic names.
- **YAML is `safe_load`/`safe_dump` throughout**, temp directories are context-managed, the
  `version` gotcha in `validate_facts` is handled, and node keys are lowercased to match Batfish's
  canonicalisation.
- **Retention sorts by `creationTimestamp`, never by name**, and a retention failure never fails
  the step.
- **Result artifacts reuse the existing `workflow_runs:read`-scoped artifact endpoint**; no new
  read path was added for the run-detail viewer.
- **Tests.** 25 Batfish test files; every executor at 100 %, `query_helpers` 98 %,
  `preview_service` 99 %; the `test_batfish_query_router_auth.py` file checks permission gating on
  all nine ad-hoc endpoints.

### 3.2 Findings

| # | Sev | Finding | Location | Fix | Publish |
|---|---|---|---|---|---|
| B1 | **M** | **A Batfish source host is not validated against the outbound policy — the doc says it must be, then says it isn't needed.** `_validate_host` accepts any non-empty string ≤ 255 chars. pybatfish builds `http://{host}:{port}/v2/...` from it (`Session.get_base_url2`, verified) and speaks plain HTTP with no auth. Every other source runs `validate_outbound_http_url` (blocks link-local incl. `169.254.169.254`, `metadata.google.internal`, loopback unless `ALLOW_LOOPBACK_SOURCE_URLS`, DNS-resolved). Consequences for a `sources.batfish:write` holder (only via an admin-granted custom role, but the permission itself is not protected): **(a)** `POST /sources/batfish/test-connection` with inline `{host, port}` is a blind reachability probe of any internal host:port, without even saving a source; **(b)** a workflow with `batfish-init-snapshot` pointing at a source whose host they control **uploads every device running-config of that run as a zip to their server** (`init_snapshot` POSTs the snapshot archive) — the same data the vault/git designs treat as sensitive. The doc's own "Security notes" section says the integration "must never … add a way to point a Batfish source at a non-local/non-`backend`-network host without equivalent protection", and the "Open items" section then records "RESOLVED … no `validate_outbound_http_url` call was needed" because `host` "is a bare hostname/IP, not a URL". It becomes a URL one line into pybatfish. | `services/batfish/source_config_service.py::_validate_host`, `::resolve_inline_connection`, `routers/sources/batfish/ops.py`, `doc/BATFISH_INTEGRATION.md` §Security notes / §Open items | Call `validate_outbound_http_url(f"http://{host}:{port}", resolve_dns=True)` from `_validate_host` (create, update, inline test) and again in `resolve_connection` (rows can predate the check). Native dev against `127.0.0.1` then needs `ALLOW_LOOPBACK_SOURCE_URLS=true`, exactly like pyATS/OpenBao — update the doc bullet and `docker/batfish/README.md`. Add the "device configs are uploaded to the Batfish container" accepted risk to `doc/SECURITY-NOTES.md` (the doc promised this "once this ships"; it has not been done). | yes |
| B2 | **M** | **Ad-hoc query and discovery endpoints bypass workflow visibility.** All nine `POST /sources/batfish/{id}/query/*` routes and both discovery routes require only `sources.batfish:read`, which the seeded read-only `viewer` role holds ("Read-only access to every resource"). Batfish networks are global on the coordinator and named `manus-workflow-{workflow_id}` by default, so a viewer can `GET …/networks`, pick another team's private workflow's network (`Workflow.visibility` defaults to `"private"`), and read its full routing table, ACL verdicts, BGP/OSPF facts, or `extractFacts` (which includes TACACS/SNMP/NTP server lists) — content that the run-detail UI only exposes to users who can see that run. The doc's security notes call these answers "themselves sensitive". Not new data per se (the configs are in git too), but a documented visibility boundary is crossed by a read-only role. | `routers/sources/batfish/{query,discovery}.py`, `services/auth/rbac_seed.py` | Short term: introduce `sources.batfish:query` for the ad-hoc endpoints and do **not** grant it to `viewer` (it is a Template-Editor feature, so pair it with `templates:write`). Medium term: in `BatfishPreviewService._resolve` and the discovery router, map `manus-workflow-<id>` networks back to the workflow row and apply the existing visibility check; networks with a custom `network_name` stay admin-only or get an owner column in a small `batfish_networks` table. | yes |
| B3 | L | **No result or cost bounds on ad-hoc queries.** `routes` with no filter serialises the entire fleet RIB through pandas → JSON → Pydantic in the API process; `nodes="/.*/"` on `extract-facts` likewise; `params` on `/query/generic` is an unbounded dict; no per-user rate limit (S9). Each call also pays pybatfish's retry policy (`Retry(total=max_retries…, backoff_factor=…)` on 429/5xx). A `sources.batfish:read` holder can keep an API worker busy for tens of seconds per request. | `routers/sources/batfish/query.py`, `services/batfish/preview_service.py` | Cap rows returned to the editor (e.g. 5 000, with a `truncated` flag on `BatfishQueryResponse`); require `nodes` or `network_prefix` for `routes` in the preview path; reuse the rate limiter from SM10. | |
| B4 | L | **Session cache: global lock during blocking construction, never evicted.** `_get_session` holds the single `asyncio.Lock` across `to_thread(Session, …)` (which loads all question templates — an HTTP round trip) and `to_thread(session.set_network, …)`; with pybatfish's 30 s timeout and connect retries, one slow coordinator serialises every Batfish call in the process behind it. Entries are never evicted, so the dict grows by one `Session` (with its loaded question catalogue) per network — one per workflow under the default naming — and sessions for a deleted or re-pointed source linger until restart. `list_networks`/`check_health` build a throwaway `Session` with `load_questions=True` on every call, including every discovery-picker open. | `services/batfish/client.py::_get_session`, `::list_networks`, `::check_health` | Per-key locks (or construct outside the lock and insert with `setdefault`); bounded LRU or idle-TTL eviction; `Session(..., load_questions=False)` for the two list-only paths. | |
| B5 | L | **Cross-workflow interference via `network_name` and `overwrite=True`.** `batfish-init-snapshot` accepts any `network_name` string; a `workflows:write` holder can name another workflow's default network (`manus-workflow-<their-id>`) or a shared production network, upload a snapshot into it with `overwrite=True`, and its retention sweep then deletes that network's older snapshots. Nothing ties a network to an owner. The doc describes the shared-network pattern as intended for the nightly production refresh, which is exactly the network worth protecting. | `workflow_steps/batfish_init_snapshot/executor.py` | Prefix overrides (`manus-named-<name>`) so a custom name can never collide with another workflow's default; document that a shared network is a shared resource; longer term the ownership table from B2 covers this too. | |
| B6 | L | **`device_id` is used verbatim as a filename in the snapshot temp dir.** `_write_device_configs` writes `configs_dir / f"{device_id}.cfg"`. Today every id is a hashed `list-<sha256>` (`device_context_from_entry`), a Nautobot UUID, or a Batfish node name derived from a config `hostname` line, so no current source can produce `/` or `..` — but the invariant is not enforced at the write site, and `sanitize_path_segment` exists one import away. | `workflow_steps/batfish_init_snapshot/executor.py::_write_device_configs` | `configs_dir / f"{sanitize_path_segment(device_id)}.cfg"`. | |
| B7 | L | **`validate-facts` git corpus is parsed on the event loop.** `_build_git_facts_corpus` reads each file in a thread but runs `yaml.safe_load` inline for up to 20 000 files × 10 MiB. Same for `_parse_nodes_yaml` on the rendered path. CPU-bound YAML parsing of a large corpus stalls the worker loop. | `workflow_steps/batfish_validate_facts/executor.py::_build_git_facts_corpus` | Parse inside the same `to_thread` call that reads the file (or `to_thread(_parse_nodes_yaml, text)`). | |
| B8 | L | **Generic-question `params` can carry pybatfish's own meta-kwargs.** `question.py` treats `question_name` and `exclusions` as accepted extra kwargs on every question; passing `question_name` renames the question instance on the coordinator. Harmless, but not something the endpoint means to expose. | `services/batfish/query_helpers.py::query_generic` | Strip `question_name`/`exclusions` from `clean_params` (or reject with 400). | |
| B9 | info | **`BatfishAPIError` messages embed pybatfish exception text** (`f"… failed: {exc}"`) and end up in step summaries and `logger.error`. Routers sanitize them to 502, so nothing leaks to HTTP clients; run logs are `workflow_runs:read`-scoped. Fine as is; noting because the same string can contain the coordinator URL. | `services/batfish/client.py` | — | |

### 3.3 Documentation drift in `doc/BATFISH_INTEGRATION.md`

- "Everything below exists on `feature/batfish` (as of this writing, not yet merged to `main`)" —
  it is on `main`.
- The "RESOLVED: no `validate_outbound_http_url` call was needed" bullet contradicts the
  "Security notes" section and is wrong (B1).
- "worth recording explicitly in `doc/SECURITY-NOTES.md` … once this ships" — not done;
  `SECURITY-NOTES.md` has no Batfish or Secret Manager entry.

---

## 4. CLAUDE.md compliance (new code only)

| Standard | Status | Notes |
|---|---|---|
| Model → Repository → Service → Router | ✅ | `SecretManagerConnection` follows it exactly; Batfish sources use the Settings-KV pattern like pyATS/ISE (documented deviation, acceptable) |
| Models exported from `core/models/__init__.py`, indexes, timestamps | ✅ | `secret_manager_connections` has `idx_secret_manager_conn_active`, `created_at`/`updated_at`; uses `Column(...)` not `Mapped[...]` (pyright noise, see §1) |
| No `text()` outside allow-list; no raw SQL | ✅ | guard passes |
| No raw exception text in 5xx | ✅ | both routers use `raise_internal_server_error`; Batfish uses `status_code=502` correctly |
| No f-string logging, no `except: pass` | ✅ | 0 / 0 in 111 files |
| Thin routers | ✅ | `routers/secret_manager.py` and the four Batfish routers delegate everything |
| Pydantic validation at boundaries | ⚠️ | `backend_config: dict[str, Any]` unvalidated at the request layer although typed sub-models exist and are unused (SM9); no `max_length` on `name`; Batfish request models are tight (`pattern`, `ge/le`, `min_length`) |
| Outbound URL policy (`core/safe_urls`) on every admin-configured HTTP target | ❌ | neither feature applies it (SM2, B1) — the first two integrations since the policy was introduced that don't |
| Production guards on TLS opt-outs | ❌ | `verify_ssl=False` honoured from a DB row outside development (SM2, same class as V1) |
| Auth on every endpoint | ✅ | 15 new routes, all with `require_permission`; permissions seeded (`secret_manager.connections:*`, `sources.batfish:*`) |
| Rate limiting on all endpoints (global rule) | ❌ | none on the new routes; two of them trigger external calls (SM10, B3) |
| Workflow-step rules (dispatch-only registry, `git_repository_id` via loader, `ValueError`/`RuntimeError`) | ✅ | `batfish-init-snapshot` and `batfish-validate-facts` use `load_git_repository`; 14 new steps registered in `step_registry.py` + `registry.yaml` |
| "External code must never import `workflow_steps`" | ✅ | respected — and it forced the good `services/batfish/facts_specs.py` relocation so the preview service shares the merge logic |
| Both lifespans (API + workers) | ✅ | `BatfishService` started/stopped in `main.py` and `worker_services.py`; secret-manager registry is lazy with `stop_secret_manager_services()` in both |
| Files ≤ 800 lines, functions < 50 lines | ✅ | largest new file 545 lines (`query_helpers.py`), executors ≤ 425; a few executors' `execute()` exceed 50 lines but are linear |
| Immutability | ✅ | frozen dataclasses for configs/specs/policies; `model_copy` everywhere in steps |
| 80 % coverage, TDD | ⚠️ | overall 83.4 %; Batfish new code ≥ 90 % almost everywhere; Secret Manager adapters/registry/config at 0 %, router 29 % (SM11) |
| Docs current | ⚠️ | CLAUDE.md still says "15 tables" (now 21 model classes) and its key-file list lacks `secret_manager.py`; `doc/SECURITY-NOTES.md` has no entry for either feature; Batfish doc drift in §3.3 |

---

## 5. Python and code-quality notes

- **Good patterns worth keeping:** `require_field` / `_or_none` as the single normalisation
  point; `CombinedQuestionSpec` / `PropertyQuestionSpec` as data-driven engines instead of
  per-step copies; `OSPF_QUESTION_KEYS` deriving the toggle table; `BatfishAnswerFailedError`
  carrying the raw answer for callers; `_InitSummary` frozen dataclass instead of a tuple;
  `generate_password` shuffling with `SystemRandom`.
- **`SecretManagerConnectionService` copies `GitRepositoryService`'s `try/except Exception:
  logger.error(...); raise` wrapper on every method.** It adds a log line and nothing else; the
  router already logs through `raise_internal_server_error`. Harmless, but the "log detailed
  context server-side" intent is already met one layer up.
- **`OpenBaoService.startup()` now serves two masters** (app boot: soft-fail is right; connection
  adapter: soft-fail is wrong — SM1). A `raise_on_failure: bool` parameter, or exposing `healthy`,
  keeps both without duplicating the login code.
- **The Infisical adapter's TOCTOU in `set_field`** (GET to decide POST vs PATCH) is documented
  and acceptable; the doc's own note that the PATCH/DELETE verb shapes are unverified against a
  real instance still stands — `docker/infisical/` exists precisely to close that, and it has not
  been run.
- **`BatfishService.check_health` and `list_networks` are byte-for-byte identical** except for
  the error strings; the docstring justifies it. Fine.
- **pyright** on the changed files: 8 errors, none substantive for the new code (4 are
  `Column` vs `Mapped` on the new model, 4 are in touched pre-existing files).

---

## 6. What to do next

Ordered by risk, then effort. Items 1–5 are what I would not ship the two features without.

**Before calling the features done**

1. **SM2** — `validate_outbound_http_url` + https-only + `verify_ssl=False` refused outside
   development for `addr`/`site_url`; restrict the connection credential to a non-SSH type;
   consider protecting `secret_manager.connections` (P3). Tests for each.
2. **B1** — same URL policy for the Batfish `host` (create, update, inline test, and
   `resolve_connection`); fix the doc bullet; add the accepted-risk entry to `SECURITY-NOTES.md`.
3. **SM1** — make `ensure_started` prove authentication for both adapters; router tests for
   auth failure.
4. **SM3** — remove (or dev-gate and git-strip) `secret-set` `fixed` mode.
5. **B2** — separate `sources.batfish:query` permission not held by `viewer`, or visibility mapping
   for `manus-workflow-*` networks.

**First hardening pass**

6. **SM4** — worker-side staleness: re-check `(is_active, updated_at)` in `get_or_create` or a
   short TTL.
7. **SM11** — the four missing adapter/registry/router test files (they would have caught 1, 3).
8. **SM5, SM9, B8** — input strictness: `field`/path regexes, `#` in the segment sanitizer,
   `max_length`s, validate `backend_config` with the existing sub-models, coerce `version`,
   strip pybatfish meta-kwargs.
9. **SM6** — cache-bypassing read + CAS in `set_field`.
10. **SM7** — `repr=False` on every secret field (also closes V6).
11. **SM8, B4, B7** — event-loop hygiene: `to_thread` in `SecretManagerService`, per-key session
    locks + eviction + `load_questions=False`, YAML parsing off the loop.
12. **SM10, B3** — rate limits on `/test` and the ad-hoc query routes; row cap on preview results.

**Backlog / docs**

13. B5 (network-name namespacing), B6 (`sanitize_path_segment` on the snapshot filename).
14. Docs: CLAUDE.md table count and key-file list; Batfish doc §3.3 items; run the Infisical
    stack once and record the verified PATCH/DELETE/version behaviour in the doc.

---

## 7. Appendix — new routes

All 15 new routes carry a permission dependency; none is anonymous.

| Route | Permission |
|---|---|
| `GET/POST /secret-manager/connections`, `GET/PUT/DELETE …/{id}` | `secret_manager.connections:read` / `:write` / `:delete` |
| `POST /secret-manager/connections/{id}/test` | `secret_manager.connections:write` |
| `GET/POST /sources/batfish`, `GET/PUT/DELETE …/{id}` | `sources.batfish:read` / `:write` / `:delete` |
| `POST /sources/batfish/test-connection` | `sources.batfish:write` |
| `GET /sources/batfish/{id}/networks`, `…/networks/{network}/snapshots` | `sources.batfish:read` (see B2) |
| `POST /sources/batfish/{id}/query/{routes,reachability,test-filters,generic,extract-facts,ospf-facts,bgp-facts,node-properties,interface-properties}` | `sources.batfish:read` (see B2) |

New workflow steps (14): `secret-get`, `secret-set`, `secret-generate`, `generate-password`,
`batfish-start-run`, `batfish-init-snapshot`, `batfish-extract-facts`, `batfish-validate-facts`,
`batfish-routing-table`, `batfish-node-properties`, `batfish-interface-properties`,
`batfish-ospf-facts`, `batfish-bgp-facts`, `batfish-path-check`, `batfish-acl-check`.
