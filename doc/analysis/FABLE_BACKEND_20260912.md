# Backend Analysis — 2026-09-12

Reviewer: Claude Fable 5.1
Scope: `backend/` (FastAPI app, Hatchet workers, workflow steps), plus the Next.js proxy where it
is part of the auth chain. Focus areas requested by the owner: the new OpenBao (Vault) integration,
token management (changed since the last audit), RBAC (changed since the last audit), CLAUDE.md
compliance, and a general security review with the goal of making the repository public.

Previous audit: `doc/analysis/FABLE_BACKEND_20260902.md`. Findings there are referenced as
`S1`–`S16`; their fixes were verified again here and are not re-litigated. New findings use fresh
prefixes: `V` (vault), `T` (tokens/auth), `R` (RBAC), `W` (webhooks / other), `C` (compliance).

## 0. Verdict in one paragraph

The backend has improved materially since 2026-09-02. All twelve release-relevant findings from
that audit are fixed and stayed fixed (verified by reading the code, not the commit messages), the
mechanical gates are green (ruff clean, four guard scripts OK, 2 534 tests passing at 84 % coverage,
pip-audit clean, git history free of committed secrets), and the OpenBao integration is, on the
whole, a careful piece of work: env-only configuration, fail-closed resolution, two least-privilege
policies, token held only in memory, write-through with rollback, sanitized KV paths, and 45 unit
tests plus an opt-in live integration suite. The RBAC grant policy (P1–P7) is implemented exactly as
documented and covered by 31 dedicated tests.

It is **close to publishable, but not yet**. Seven items should be fixed first. None is a remote
pre-auth compromise; all are either a way for a semi-trusted insider to exceed the documented
security model, a way for an anonymous client to degrade availability of login, or a gap that
undermines what the vault feature promises:

1. **T1** — the login rate limiter is keyed on a spoofable or collapsed client IP. Behind the
   shipped Next.js proxy an anonymous client can either bypass it (spoofed `X-Forwarded-For`) or
   lock any username out of login with five requests a minute.
2. **R1** — a `users:write` holder can reset any non-admin's password and log in as them, inheriting
   permissions the actor does not hold. This breaks the P2 "no delegation beyond own rights" model.
3. **R2** — the last-admin invariant (P6) counts deactivated admins, so the last *active* admin can be
   removed and the lifespan self-heal will not fire.
4. **V1** — `VAULT_VERIFY_SSL=false` is honoured in production (only the `https://` scheme is checked).
5. **V2** — vault-backed SSH private keys are written to `data/ssh_keys/` in plaintext and never
   deleted, which defeats the purpose of storing them in OpenBao.
6. **V3** — deleting a vault credential only soft-deletes the latest KV v2 version; every previous
   secret version stays readable by the runtime role.
7. **V4** — token renewal is scheduled from configuration, not from the lease OpenBao actually
   returned, so a mismatched role silently produces one failed step per expiry.

Everything else is medium or low and listed with a concrete fix in the sections below.

---

## 1. What was run

| Check | Result |
|---|---|
| `ruff check .` (backend, rules E/F/I/UP/B/S/ASYNC) | clean |
| `scripts/check_asyncio_run.py` | OK |
| `scripts/check_http_500_leaks.py` | OK |
| `scripts/check_router_repositories.py` | OK |
| `scripts/check_text_sql.py` | OK |
| `python -m pytest` (unit, coverage ratchet 81 %) | 2 534 passed, 0 failed, coverage 84.02 %, 28.7 s |
| `pyright` (basic, advisory) | 158 errors (tracked in `doc/OPEN_TODOS.md`, triaged as non-runtime) |
| `pip-audit -r requirements.txt -r requirements-dev.txt` | no known vulnerabilities (1 ignored, PYSEC-2026-2858) |
| AST scan of every route decorator (216 routes) | 7 unauthenticated by design, 6 authenticated own-data routes, 203 with a permission dependency |
| grep: f-string logging, bare `except:`, `shell=True`, `eval`/`exec`/`pickle`/`yaml.load`, `os.environ[...] =` | 0 each |
| grep: `except ...: pass` | 18 (was 13) |
| grep: `verify=False` | 3 (Nautobot / ISE / pyATS opt-in per-source clients, documented in `doc/SECURITY-NOTES.md`) |
| grep: `# noqa: S*` in non-test code | 15 (6× S101 assert, 4× S105 sandbox constants in `scripts/ise_*`, 4× S501, 1× S324 md5 checksum) |
| grep: secret values in log calls | none found |
| `git log --all` for committed `.env`, keys, `oidc_providers.yaml` | none, ever (384 commits) |
| Tracked `LICENSE` / `SECURITY.md` | Apache-2.0 present; no `SECURITY.md` |

Backend churn since the previous audit: 57 commits touching `backend/`, roughly 90 non-test files
changed, including the vault package, the CI/CD change-request pipeline (webhooks, change requests),
the `CredentialManager` facade, the shared-secret credential type, and the `StepRunner` /
`workflow_run` package splits.

---

## 2. Previous findings — status re-verified

| # | Finding | Status today | Evidence |
|---|---|---|---|
| S1 | OIDC takeover by username | Fixed | `provision_or_get_user` matches on `(provider, sub)` only; username collision → `OIDCIdentityConflictError` |
| S2 | `users:write` escalates to admin | Fixed, with one residual gap (**R1** below) | P1–P7 in `RBACService` / `UserService` |
| S3 | System roles renameable | Fixed | `update_role` P5 |
| S4 | Docker root / dev defaults | Fixed | `useradd manus` in all three images, privileges dropped in entrypoints; compose requires `SECRET_KEY`, `INITIAL_PASSWORD`, `CREDENTIAL_ENCRYPTION_KEY`; `ENV` defaults to `production` |
| S5 | No revocation / absolute lifetime | Fixed | `tv`, `sid_iat`, `jti`, `iat`; `SESSION_MAX_AGE_HOURS` |
| S6 | No password policy | Fixed | `password_policy.py`, `must_change_password` |
| S7 | `os.environ` mutation in git | Fixed | `build_git_env_overrides` passes `env=` |
| S8 | Prefix path check | Fixed | `services/git/paths.py::resolve_within_repo` |
| S9 | No rate limiting beyond login | **Open** | see T1 for why the existing limiter also needs work |
| S10 | Bootstrap admin re-granted on every boot | Fixed | `role_has_members("admin")` gate |
| S11 | DDL without lock | Fixed | `pg_advisory_xact_lock` |
| S12 | KDF / secret-key checks | Fixed | `KDF_ITERATIONS` via Settings, `lru_cache`d key |
| S13 | OIDC nonce / PKCE / secret in YAML | Fixed | nonce + S256 PKCE, `OIDC_<ID>_CLIENT_SECRET` |
| S14 | Inventories owned by username string | **Open** | still `created_by: str`; see R6 |
| S15 | Certificate upload size cap | **Open** | `upload()` still reads the whole body |
| S16 | `oidc/debug` info | Open (accepted) | still dev-tools + permission gated |

---

## 3. OpenBao (Vault) integration

Files reviewed in full: `core/vault.py`, `services/vault/{config,auth,client,token_manager,cache,exceptions}.py`,
`services/credentials/{credentials_service,manager,secrets,source_credentials,exceptions}.py`,
`routers/credentials.py`, `models/credentials.py`, `core/models/credentials.py`,
`repositories/credentials_repository.py`, `core/config.py` (vault block), `core/production_guards.py`,
`service_factory.py` (vault accessors), `main.py` / `hatchet/worker_services.py` lifespans,
`doc/VAULT_INTEGRATION.md`, `backend/.env.example`, `docker/docker-compose.yml`.

### 3.1 What is done well

- **Configuration boundary.** Every setting is an environment variable read once in `Settings`,
  structurally validated (`_validate_vault`: URL shape, auth method, period/buffer ordering, cache
  TTL range) and then production-hardened in `production_guards` (https required, token auth
  refused, AppRole material for both roles required, cert material required). Nothing is read from
  the Settings KV table or from OpenBao itself. This is the right shape.
- **Dev-only token auth is double-gated**: refused in `build_auth_strategy` and in
  `production_guards`, so it cannot be reached by a code path that skips one of them.
- **Two policies, two tokens.** The runtime role (`manus-app`, read-only on
  `manus/data/credentials/*`) and the management role (`manus-manage`) are separate `OpenBaoService`
  instances with separate tokens. The write-capable client is injected only by
  `routers/credentials.py::_service`; `service_factory.build_credentials_service` omits it, so step
  and worker code is structurally read-only, not merely policy-restricted. Good design.
- **Token lifecycle.** The client token lives only in `VaultTokenManager._token` (never file, DB or
  Redis). A periodic token is renewed by an `asyncio` loop; a 403 on renew or on any request
  invalidates the token and the next request logs in again. Startup login failure is a soft fail
  (logged at ERROR) that leaves `local` credentials working — correct fail-closed-per-credential
  semantics.
- **KV path derivation** is `credentials/{sanitised-name}-{id}` with `[^a-zA-Z0-9_-] → _`, so a
  user-controlled credential name cannot traverse into another path or another mount. The `id`
  suffix keeps a global and a private credential with the same name apart. The path is frozen at
  create time and stored on the row, so a rename never orphans the secret.
- **Write-through with rollback.** Create is flush → KV write → commit; any `VaultError` rolls the
  row back, so a `vault` row without a backing secret cannot exist. `vault_secret_fields` lets the
  list view render `has_*` flags without an OpenBao round-trip, so metadata keeps working when
  OpenBao is down.
- **No secret in the DB for vault rows** (`password_encrypted` etc. are `NULL`), no secret in any
  response (`_to_dict` exposes only `vault_path` and field names), and the reveal endpoint stays
  behind the separate `credentials:reveal` permission.
- **Error mapping** is complete: every `VaultError` becomes `CredentialVaultUnavailableError`, which
  the router turns into a sanitized 503 `{message, error_id}` via `raise_internal_server_error`.
  `git/auth.py` re-raises the vault errors out of its otherwise-forgiving `except`, so a vault
  outage on a clone fails loudly instead of degrading to "no auth".
- **Cache discipline.** `InProcessTTLCache` is thread-safe, hands back copies, caches only
  successful reads, and is refreshed by writes / invalidated by deletes on the same client.
- **Thread-safety.** `httpx.Client` is thread-safe; `VaultTokenManager` serialises login/renew with a
  `threading.Lock`; the sync client is used from FastAPI `def` handlers (threadpool) and worker
  threads, with the renew loop as the only async part. The deviation from "async httpx everywhere"
  is deliberate and documented.
- **Tests.** 45 unit tests across five files (client URL/body shaping, status mapping, cache,
  auth strategies, SecretID-from-file, dev-only guard, renew/403 fallback, service dispatch on a
  real SQLite `credentials` table, rollback on KV failure, router 422/503 mapping), plus a live
  integration suite that exercises policy enforcement and revoked-token re-login.
- **Docs.** `doc/VAULT_INTEGRATION.md` is accurate to the code (every claim was checked) and includes
  a usable ops runbook with policies, AppRole creation and SecretID rotation.

### 3.2 Findings

Severity: **H** = fix before publishing, **M** = fix in the first hardening pass, **L** = backlog.
"Publish" column marks the items I would not ship without.

| # | Sev | Finding | Location | Fix | Publish |
|---|---|---|---|---|---|
| V1 | M | **`VAULT_VERIFY_SSL=false` is honoured outside development.** `production_guards` checks that `VAULT_ADDR` starts with `https://` but never looks at `vault_verify_ssl`, so a production deployment can disable certificate verification and send the AppRole SecretID, the client token and every secret over a MITM-able channel. Token auth and `http://` are already refused outside development; this is the same class of setting. | `core/production_guards.py`, `core/config.py` | Add `vault_verify_ssl` to `validate_non_development_secrets` and raise unless `environment == "development"`. Operators with a private CA use `VAULT_CACERT`, which already works. | yes |
| V2 | M | **Vault-backed SSH private keys are materialised on disk and never removed.** `get_ssh_key_path` for a `vault` row reads the key from OpenBao and calls `_write_ssh_key_file`, writing the plaintext key to `data/ssh_keys/<prefix><name>` (mode 0600) on every resolution. `delete_credential` skips `_delete_ssh_key_file` for vault rows (the `elif` at line ~394 only runs for local ones), and a rename leaves the old file behind. The result: after the first git operation, the private key an operator chose to keep in OpenBao lives permanently on the app host's filesystem and survives credential deletion. The same permanent-export design exists for `local` keys, but there the DB already holds the ciphertext on the same host; for vault rows it silently changes the storage guarantee. | `services/credentials/credentials_service.py::get_ssh_key_path`, `_write_ssh_key_file`, `delete_credential` | Short term: delete the key file on `delete_credential` and on rename for vault rows too. Right fix: for vault rows write the key to a per-operation temporary file (`tempfile.NamedTemporaryFile` in a 0700 directory under `data/ssh_keys/tmp/`) and remove it in a `finally` around the git call (`setup_auth_environment` is already a context manager and is the natural place). Document that `local` keys are exported permanently. | yes |
| V3 | M | **Delete is a KV v2 soft-delete; old versions remain readable.** `delete_kv` issues `DELETE /v1/<mount>/data/<path>`, which only marks the *latest* version deleted; metadata and every previous version stay and can be `undelete`d. Updates go through `_merge_vault_secret` → `write_kv`, which creates a new version and leaves the superseded secret readable by the runtime role via `GET …/data/<path>?version=N` (the `manus-app` policy grants `read` on the data path). So a rotated device password, or a deleted credential, is still retrievable from OpenBao by anything holding the runtime token. The `manus-manage` policy in the runbook already grants `delete` on `manus/metadata/credentials/*` — the code just doesn't use it. | `services/vault/client.py::delete_kv`, `credentials_service.py::delete_credential`, `_merge_vault_secret`, `doc/VAULT_INTEGRATION.md` §KV layout | On credential delete call `DELETE /v1/<mount>/metadata/<path>` (destroys all versions). On update, either `POST /v1/<mount>/destroy/<path>` for the previous version (add `manus/destroy/credentials/*` `update` to the manage policy) or set `max_versions=2` on the mount and document that one prior version is retained for rollback. State the chosen retention explicitly in the doc. | yes |
| V4 | M | **Renewal cadence is configuration-driven, not lease-driven.** `_renew_loop` sleeps `VAULT_TOKEN_PERIOD_SECONDS − VAULT_RENEW_BUFFER_SECONDS` (default 3000 s). The `lease_duration`, `renewable` and `period` values returned by the login are stored on `VaultToken` but never consulted. If the OpenBao role's `token_period`/`token_ttl` is shorter than the configured period (a very easy misconfiguration — the runbook and the env var must be kept in sync by hand), or the role issues a non-periodic token, the token expires between renewals. The next KV read gets 403 → `_tokens.invalidate()` → `VaultPermissionError` → **that request fails** (one workflow step fails, one credential reveal 503s) and only the *following* request re-logs-in. The failure repeats once per expiry, indefinitely, with nothing in the logs pointing at the cause except the 403 warning. | `services/vault/client.py::_renew_loop`, `_request`; `services/vault/token_manager.py` | (a) Schedule the next renew from the lease actually returned: `next = max(60, min(cfg_interval, lease_duration − buffer))`, recomputed after every login/renew. (b) In `_request`, on 403 re-login once and retry the request once before raising, so a single expiry is transparent. (c) At startup log a WARNING if `lease_duration < token_period_seconds` or `renewable is False` under AppRole. | yes |
| V5 | L | **Hatchet workers hold a write-capable management token they never use.** `start_vault_services()` builds and logs in *both* clients unconditionally, and `worker_services.start_all` calls it. Worker code can only reach `CredentialsService` without a writer, so the management token in the worker process is dead weight that widens the blast radius of a worker compromise and makes `production_guards` demand management material for every worker deployment. | `core/vault.py::start_vault_services`, `hatchet/worker_services.py` | Give `start_vault_services(*, with_management: bool)` a flag; API lifespan passes `True`, workers `False`. Relax the guard so management material is required only where management is started. | |
| V6 | L | **Secrets in dataclass `repr`.** `VaultToken.client_token` and `VaultConfig.secret_id` / `token` / `client_key` are frozen dataclasses with the default generated `__repr__`. Nothing logs them today, but any `%r`, a debugger, or an error tracker that captures locals (`exc_info=True` is used on the login failure path) would print the SecretID or client token. | `services/vault/auth.py`, `services/vault/config.py` | `field(repr=False)` on every secret-bearing field; add a one-line test asserting `"secret" not in repr(cfg)`. | |
| V7 | L | **403 conflates "token invalid" with "policy denied".** Every 403 invalidates the token and forces a fresh AppRole login on the next call. A path that is legitimately denied (policy typo, wrong mount) therefore triggers a login storm and floods the OpenBao audit log, and it masks the real cause. | `services/vault/client.py::_request` | After a 403, call `GET /v1/auth/token/lookup-self`; only invalidate if that also fails. Or combine with V4(b): re-login + retry once, then raise `VaultPermissionError` *without* invalidating again. | |
| V8 | L | **Cross-client cache staleness inside the API process.** The management client's `write_kv`/`delete_kv` refresh only *its own* cache; the runtime client in the same process keeps serving the old secret for up to `VAULT_CACHE_TTL_SECONDS` (45 s) after a rotation or deletion. Documented as accepted, but the two singletons live in one process so the fix is one line. | `credentials_service.py::_merge_vault_secret`, `delete_credential` | After a successful management write/delete, call `self._get_vault_reader().invalidate(path)` (add a thin `invalidate` passthrough on `OpenBaoService`). Workers still see the change after their TTL, which is fine. | |
| V9 | L | **Delete is fail-open toward orphaned secrets.** On any `VaultError`, `delete_credential` logs a warning and deletes the DB row anyway, leaving the KV entry with no pointer to it (and, with V3, all its versions). "Fail closed" is the stated design everywhere else. | `credentials_service.py::delete_credential` | Fail the delete with `CredentialVaultUnavailableError` (503) so the operator retries when OpenBao is back; or record the orphaned path in a table for a sweep. | |
| V10 | L | **Update ordering and no compare-and-set.** `_merge_vault_secret` writes OpenBao *before* `self._repo.update(...)` commits; a DB failure after the KV write leaves `vault_secret_fields` stale (only the `has_*` badges are wrong). The read-merge-write is not atomic — two concurrent updates clobber each other silently. | `credentials_service.py::update_credential`, `services/vault/client.py::write_kv` | Send KV v2 `options.cas = <version from the read>` on update writes and map 400 "check-and-set" to a 409. Minor. | |
| V11 | L | **Large secret bodies are unbounded.** `CredentialCreate.password`, `ssh_private_key` and `ssh_passphrase` have no `max_length`; a multi-megabyte value goes straight into OpenBao (or the Fernet column) and the in-process cache. | `models/credentials.py` | `max_length` of 64 KiB for keys and 1 KiB for passwords/passphrases. | |
| V12 | L | **No readiness signal for OpenBao.** `GET /credentials/vault/status` is a pure settings read and `/health/ready` ignores the vault. When the startup login soft-fails, the only signal is an ERROR log line; `_healthy` is set but never read. Documented as deferred. | `main.py::health_ready`, `services/vault/client.py` | Expose `OpenBaoService.healthy` and add a `vault_ok` field to the ready response when `VAULT_ENABLED`. | |
| V13 | L | **SecretID file permissions are not checked.** `resolved_secret_id()` reads `VAULT_SECRET_ID_FILE` on every login (correct — supports in-place rotation) but a world-readable file goes unnoticed. | `services/vault/config.py` | Log a WARNING if `stat().st_mode & 0o077`. | |
| V14 | L | **Runbook recommends `secret_id_ttl=0` and `secret_id_num_uses=0`.** That is the most convenient setting but it makes a leaked SecretID valid forever. OpenBao's guidance is a bounded TTL with rotation. The rotation section (every ~90 days) is good; the two zeros contradict it. | `doc/VAULT_INTEGRATION.md` §Ops runbook | Recommend `secret_id_ttl=2160h` (90 days) so an un-rotated SecretID expires on its own, and keep `secret_id_num_uses=0` (redeploys). | |

### 3.3 Best-practice checklist (OpenBao / HashiCorp guidance)

| Practice | Status |
|---|---|
| Machine auth via AppRole (not a static token) in production | ✅ enforced by guards |
| RoleID and SecretID delivered separately; SecretID via file / Docker secret | ✅ supported and documented |
| Least-privilege policies, separate read and write identities | ✅ two policies, two tokens; ⚠️ workers get the write token too (V5) |
| No `list` capability granted | ✅ |
| Periodic tokens with renew-self | ✅; ⚠️ renew cadence not tied to the returned lease (V4) |
| Token never persisted | ✅ |
| TLS verification on | ⚠️ can be disabled in production (V1) |
| Namespace support | ✅ header sent on every call |
| CIDR-bound roles | ✅ documented |
| SecretID rotation / bounded TTL | ⚠️ documented rotation, but TTL 0 (V14) |
| KV v2 versioning handled deliberately (destroy / max_versions) | ❌ (V3) |
| Secrets not cached beyond need | ✅ 45 s in-process, copies returned, never on failure |
| No secret in logs / reprs / responses | ✅ logs and responses; ⚠️ reprs (V6) |
| Health / readiness visible to operators | ❌ (V12) |
| Fail closed when unreachable | ✅ for reads; ⚠️ delete is fail-open (V9) |

---

## 4. Token management

Files reviewed: `core/auth.py`, `services/auth/auth_service.py`, `routers/auth.py`, `models/auth.py`,
`services/auth/login_rate_limiter.py`, `core/client_ip.py`, `services/auth/oidc_service.py`,
`routers/oidc.py`, `core/models/users.py`, `frontend/src/lib/api-proxy.ts`,
`frontend/src/app/api/auth/login/route.ts`.

### 4.1 What is correct

- **Claims and verification.** Every token carries `sub`, `user_id`, `iat`, `sid_iat`, `jti`, `tv`,
  `exp`; HS256 is pinned in every `jwt.decode`; `user_id` is `isinstance`-checked; `exp` is clamped
  so it never outlives `sid_iat + SESSION_MAX_AGE_HOURS`.
- **Revocation.** `token_version` is bumped on logout, self-service password change, admin password
  change, username change and deactivation; `_load_active_user` rejects a stale `tv`; refresh is
  strict (requires numeric `tv` and `sid_iat`). Verified each bump site in `AuthService`,
  `UserService.update_user` and `UserService.set_active`.
- **Absolute session lifetime** is enforced on every request (`_load_active_user`) and on refresh,
  and a password change deliberately restarts it and returns a fresh session so the forced-change
  flow doesn't bounce to login.
- **Forced password change** is enforced in both `get_current_user` and `_require_active_user_id`,
  so a router-level `require_permission` alone still blocks; only `/auth/me`, `/auth/change-password`,
  `/auth/refresh` and `/auth/logout` use the allow-variant. The `is True` check is deliberate and
  explained.
- **Login** is constant-time for unknown users (dummy Argon2 hash), the change-password endpoint is
  rate-limited per user, and the OIDC flow has nonce, S256 PKCE, `redirect_uri` allow-list,
  state-in-Redis (fail-closed with 503 when the cache is down), `iss`/`aud` checks and constant-time
  nonce compare.
- **Transport** is unchanged and correct: HTTP-only cookie set by the Next.js route, `Authorization`
  and `Cookie` stripped before forwarding, `Set-Cookie` and `Location` stripped on the way back.
- **Route coverage.** The AST scan finds exactly 7 unauthenticated routes (`login`, `refresh`, the
  four OIDC routes, the signed webhook) and 6 authenticated own-data routes (`/auth/me`,
  `/auth/change-password`, `/auth/logout`, `dashboard/layout` GET/PUT, `rbac/users/me/permissions`).
  All 203 others carry a `require_*` dependency.

### 4.2 Findings

| # | Sev | Finding | Location | Fix | Publish |
|---|---|---|---|---|---|
| T1 | **H** | **Login rate limit is keyed on a client IP the client controls, or on no client IP at all.** The key is `f"{client_host}:{username}"`. `_get_client_host` (and its twin `core/client_ip.py::resolve_client_host`, used by the webhook) honours `X-Forwarded-For` when the direct peer is in `TRUSTED_PROXY_IPS` and then takes the **first** entry. Two deployment cases, both broken: **(a)** `TRUSTED_PROXY_IPS` contains the Next.js host (the documented intent). `api-proxy.ts::buildForwardHeaders` copies every incoming header except `authorization`, `cookie` and hop-by-hop, so the browser's own `X-Forwarded-For` reaches the backend verbatim (and any nginx/traefik in front *appends*, keeping the client's value first). An anonymous client rotates a fake XFF per request and the limiter never trips — unlimited password attempts. **(b)** The shipped `docker/docker-compose.yml` sets `TRUSTED_PROXY_IPS: ""`. Then every request is keyed on the Next.js container IP, i.e. the key collapses to **per-username**. `check()` runs *before* authentication and only a *successful* login clears the bucket, so five wrong passwords a minute against `admin` (or any known username) lock that user out of login for as long as the attacker keeps sending. That is a trivial, anonymous, remote denial of service against the front door. | `routers/auth.py::_get_client_host`, `core/client_ip.py`, `frontend/src/lib/api-proxy.ts`, `docker/docker-compose.yml` | (1) In `api-proxy.ts`, strip the incoming `x-forwarded-for` / `x-real-ip` and set `X-Forwarded-For` to the Next.js server's view of the client (Next exposes it via the request's `x-forwarded-for` set by the Node server, or `request.ip`; if neither is trustworthy in your ingress, take it from the ingress header you control). (2) In the backend, walk the XFF list from the **right** and take the first entry that is not in `TRUSTED_PROXY_IPS` — never the leftmost. (3) Make the limiter two-dimensional: a per-IP budget (say 20/min) *and* a per-username budget that backs off (progressive delay or a 15-minute lock after 10 failures) instead of a hard 5/min, so one user cannot be locked out by an anonymous stranger. (4) Set `TRUSTED_PROXY_IPS` correctly in compose (the frontend service name resolves; a static subnet is fine) and document it as required. Add a test that a spoofed XFF from an untrusted peer is ignored and that the rightmost-untrusted rule is used. This also fixes the webhook limiter (W1). | yes |
| T2 | L | **`PUT /users/{id}` lets a `users:write` holder change their *own* password and username without the current password.** P1 (`assert_not_self`) covers roles and overrides; `UserService.update_user` only calls `may_touch_target`, which allows self when the actor is not an admin (and admins bypass anyway). This sidesteps the current-password check that `/auth/change-password` exists for (protection when a session is hijacked) and, combined with S14, enables the inventory-inheritance rename (R6). | `services/users/user_service.py::update_user` | Call `assert_not_self` for password and username changes; self-service goes through `/auth/change-password`. | |
| T3 | L | **Legacy-token tolerance can be dropped before release.** `_load_active_user` accepts a token without `tv` or `sid_iat` (the `isinstance` guards exist for pre-S5 tokens and for test doubles). No such token exists outside a developer's browser, so publishing is the moment to make both claims mandatory and delete the tolerance (fix the test doubles instead). | `core/auth.py::_load_active_user` | Reject when `tv` or `sid_iat` is missing or non-numeric. | |
| T4 | L | **`REFRESH_TOKEN_MAX_AGE_HOURS` (24) exceeds `SESSION_MAX_AGE_HOURS` (12).** The absolute cap makes the extra window unreachable, but the two settings are not validated against each other and the docstring still describes the 24 h window as the boundary. | `core/config.py` | Validate `refresh_token_max_age_hours <= session_max_age_hours`, or drop the setting. | |
| T5 | L | **Logout revokes every session of the user, on every device.** A consequence of using `token_version` as the only revocation primitive. Reasonable, but users will not expect a phone logout to end the laptop session. `jti` is minted and never used. | `routers/auth.py::logout` | Either document the behaviour in the UI copy, or keep a short Redis denylist keyed by `jti` (TTL = remaining `exp`) for per-session logout and reserve the `tv` bump for password/deactivation. | |
| T6 | L | **OIDC identity binding for existing accounts does not exist.** CLAUDE.md says an admin binds an identity "explicitly (`oidc_provider`/`oidc_subject` on `UserUpdate`)". `models/rbac.py::UserUpdate` has neither field and no endpoint writes `oidc_subject` (verified by grep across `models/`, `routers/`, `services/users/`). Today the only way to link an IdP identity to a pre-existing local account is a manual DB edit. Not a vulnerability (the refusal path is the safe one), but the doc promises a feature that isn't there. | `models/rbac.py`, `routers/users.py`, `CLAUDE.md` | Either add the two fields to `UserUpdate` behind an admin-only check (P3 territory: it is an identity change) and a uniqueness error mapping, or fix the doc to say "not supported; edit the row". | |

---

## 5. RBAC

Files reviewed: `services/auth/rbac_service.py`, `repositories/rbac_repository.py`,
`routers/rbac/{roles,permissions,user_access}.py`, `services/users/user_service.py`,
`routers/users.py`, `repositories/user_repository.py`, `core/models/rbac.py`, `models/rbac.py`,
`services/auth/rbac_seed.py`, `tests/unit/test_rbac_elevation.py`, `tests/unit/test_users_router.py`.

### 5.1 What is correct

Every rule in the P1–P7 table in CLAUDE.md was traced to code and to at least one test:

| Rule | Implementation | Test |
|---|---|---|
| P1 no self-modification of roles/overrides, no self delete/deactivate | `assert_not_self` in all four user↔role/override methods; `_assert_can_remove` | `test_actor_cannot_delete_self`, `_deactivate_self`, `users_write_holder_cannot_override_protected_permission_for_self` |
| P2 grant only what you hold | `assert_actor_holds` on override grant, role-permission grant, non-system role assignment | `cannot_override_permission_they_do_not_hold`, `cannot_add_unheld_permission_to_custom_role`, `cannot_assign_custom_role_containing_unheld_permission` |
| P3 `rbac.*` / `users` / `system.*` need admin | `_is_protected` + `assert_actor_holds`; deny-override on a protected permission also needs admin | `cannot_override_protected_permission_for_self` |
| P4 touching an admin needs admin | `may_touch_target` on every user-targeted mutation incl. `update_user` and `_assert_can_remove` | `users_write_holder_cannot_touch_admin_user` |
| P5 system roles immutable | `update_role` rejects rename; router rejects delete; `create_role(is_system=True)` needs admin | `system_role_cannot_be_renamed`, `non_admin_actor_cannot_create_system_role` |
| P6 last admin | `assert_not_last_admin` on admin-role removal, deactivate, delete | `last_admin_cannot_lose_admin_role`, `cannot_remove_last_admin`, `delete_last_admin_403` |
| P7 internal callers bypass | `actor_user_id=None` short-circuits every helper | `actor_none_bypasses_policy` |

Also verified: precedence override → role → deny in `has_permission`; `RolePermission.granted=False`
is treated as "not granted" (not a deny); every mutating router passes `current_user.id` and maps
`AccessDeniedError` to 403; the bootstrap admin is re-granted only when nobody holds the role; the
`admin_reseed_rbac` wipe path re-grants deliberately and says so; all RBAC and user routes carry
`users:*` or `rbac.*:*` permissions, which are themselves protected (P3), so the only way to obtain
them is from an admin. Permissions are evaluated per request from the DB with no cache, so a change
takes effect on the next request.

### 5.2 Findings

| # | Sev | Finding | Location | Fix | Publish |
|---|---|---|---|---|---|
| R1 | **M** (H under the documented model) | **Password reset is account takeover, and it is not delegation-bound.** A `users:write` holder who is not an admin may call `PUT /users/{id}` with a new `password` for any target that is not an admin (P4 only shields admins). The actor then logs in as the target, satisfies the `must_change_password` prompt themselves, and now acts with the target's *full* effective permissions — including ones the actor never held (`credentials:reveal`, `netmiko:execute`, `change_requests:approve`, a custom role with `workflows:execute`). P2 forbids granting an unheld permission through an override or a role; resetting the password hands over all of them at once. Username change has the same shape (rename the target, then create a new user with the old name — no takeover, but identity confusion). | `services/users/user_service.py::update_user` | Treat a password reset (and username change) as a grant of the target's effective permissions: `self._rbac.assert_actor_holds(actor_user_id, [p for p, _ in self._rbac.get_effective_permissions(user_id)])` before applying it, so a non-admin can only reset users whose rights are a subset of their own. Simpler alternative: require admin for password reset and username change of *any* user (make `users:write` non-admin usage mean "create user, activate pending OIDC user, assign ≤ own rights"). Add the test. | yes |
| R2 | **M** | **Last-admin invariant counts deactivated admins.** `assert_not_last_admin` and `role_has_members` use `get_users_with_role`, which has no `is_active` filter. With admins A (active) and B (deactivated), A can be deactivated, deleted, or stripped of `admin` (P6 sees "2 members"). No active admin remains, and the lifespan self-heal in `main.py` does not fire because the role still "has members" (B). Recovery needs a DB edit. | `repositories/rbac_repository.py::get_users_with_role`, `services/auth/rbac_service.py` | Add `User.is_active.is_(True)` to the count used by P6 and by `role_has_members` (keep the unfiltered variant for the roles UI). Test: one active + one inactive admin → removing the active one is refused. | yes |
| R3 | L | **Reactivation bypasses P4.** `UserService.set_active(user_id, True)` calls `self._repo.set_active` directly; only the `False` branch runs `_assert_can_remove` / `may_touch_target`. A non-admin `users:write` holder can therefore reactivate a deactivated *admin* (a P4 violation) and, with R1, reset their password. The same call path is how pending OIDC users are approved, which is intended and must keep working. | `services/users/user_service.py::set_active` | Call `may_touch_target(actor_user_id, user_id)` on the activate branch too (it already returns early for non-admin targets, so OIDC approval is unaffected). | |
| R4 | L | **Catalog permissions can be deleted.** `rbac.permissions:delete` deletes a permission row; FK cascades remove it from every role and override, including `admin`. `has_permission` then returns `False` for everyone until the next restart re-seeds. Also `rbac.permissions:write` creates arbitrary `resource:action` rows that no router checks (harmless). Both permissions are protected (P3), so only an admin can hand them out; this is an availability foot-gun for admins rather than an escalation. | `routers/rbac/permissions.py::delete_permission`, `services/auth/rbac_seed.py` | Refuse to delete a permission that is in `DEFAULT_PERMISSIONS` (409), or mark seeded permissions `is_system=True` like roles. | |
| R5 | L | **Deleting a custom role ignores P4.** `rbac.roles:delete` on a non-system role removes it from every holder, including admins, with no actor check. Pure privilege reduction, so not exploitable, but inconsistent with "any change to an admin requires admin". | `services/auth/rbac_service.py::delete_role` | Optional: `_require_admin_actor` when any current holder is an admin. | |
| R6 | L | **S14 is still open and now has a self-rename path.** Inventories are owned by `created_by: str`. With T2 a `users:write` holder can rename themselves to a departed user's username and inherit that user's private inventories. | `core/models/inventories.py`, `services/users/user_service.py` | Add `owner_user_id` FK (as `credentials` did) and fix T2. | |
| R7 | L | **`has_permission` is 2 + 2N queries per check** and `require_permission` plus router-level `get_current_user` load the `User` row twice per request (noted last time, still true). Not a security issue; it is on every request. | `services/auth/rbac_service.py::has_permission` | One `EXISTS` over `user_roles ⋈ role_permissions` after the override lookup. | |
| R8 | info | **Deny-override on a non-protected permission needs no actor check.** A `users:write` holder can deny any non-protected permission to any non-admin user. Consistent with the model (reduction only) — noting for completeness. | — | — | |

---

## 6. Other security findings since the last audit

New surfaces reviewed: `routers/webhooks.py`, `services/change_requests/{webhook_service,change_request_service,repo_lock}.py`,
`core/webhook_signatures.py`, `core/client_ip.py`, `routers/change_requests.py`,
`repositories/change_request_repository.py`, `core/models/{git,change_requests}.py`,
`services/git/repository_service.py`, `models/git_repositories.py`, `routers/workflow_crypto_attribute.py`,
`core/passphrase_cipher.py`, `routers/certificates.py`, `services/certificates/certificate_service.py`,
`services/workflow_context/secret_fields.py`, `services/git/{auth,ssh_command}.py`.

What is correct: the webhook is the single deliberate anonymous entry point and it fails closed
without a configured secret; GitHub HMAC-SHA256 and GitLab token are compared with
`hmac.compare_digest`; delivery IDs are de-duplicated for 24 h; the secret is Fernet-encrypted at
rest and never returned (`has_webhook_secret` only); the change-request state machine uses
conditional `UPDATE`s so a UI click racing a webhook yields one deploy run; change-request reads
enforce workflow visibility (`_assert_visible`, `list_visible`); the shared-secret cipher
(`passphrase_cipher.py`) is AES-256-GCM with a per-token random salt and nonce and PBKDF2 at the
configured iteration count, and the "test" endpoints reveal nothing stored; git SSH now uses
`StrictHostKeyChecking=accept-new` with a dedicated known-hosts file; `add-to-system` lost its
`require_dev_tools` gate in `cf5abfe` but stays behind `system.certificates:write`, takes no user
input into the subprocess, and the filename is regex-validated after `Path(...).name`.

| # | Sev | Finding | Location | Fix | Publish |
|---|---|---|---|---|---|
| W1 | M | **Webhook rate limit and replay protection share T1's client-IP weakness and the login limiter's 5/min budget.** `resolve_client_host` has the same leftmost-XFF logic. A GitHub push storm (or any client behind the same proxy IP) hits `429` after five deliveries a minute per repo, and a spoofed XFF evades the limit entirely. Replay dedup depends on Redis being up (`cache is None` → no dedup) — acceptable given HMAC, but worth a log line. | `core/client_ip.py`, `services/change_requests/webhook_service.py` | Fix with T1(2). Give the webhook its own budget (e.g. 60/min per repo) rather than reusing `LOGIN_RATE_LIMIT_ATTEMPTS`. | with T1 |
| W2 | L | **No minimum length or entropy on `webhook_secret`.** `GitRepositoryRequest.webhook_secret: str \| None` accepts `"a"`. A one-character HMAC key makes signature forgery trivial for anyone who can reach the endpoint. | `models/git_repositories.py` | `min_length=16` (GitHub recommends a random 20+ byte string); reject on update as well. | |
| W3 | L | **Non-ASCII signature header → unhandled `TypeError` → 500.** `hmac.compare_digest` raises `TypeError` when given two `str` values that are not both ASCII. Starlette decodes headers as latin-1, so `X-Gitlab-Token: é…` (or a non-ASCII `X-Hub-Signature-256`) reaches `verify_gitlab_token` / `verify_github_signature` and blows up before the comparison. The generic 500 leaks nothing, but it is an unauthenticated path that should never 500. | `core/webhook_signatures.py` | Compare `.encode("utf-8")` bytes on both sides. | |
| W4 | L | **`repo_stage_lock` is fail-soft twice.** Without Redis it proceeds unlocked; on a 90 s acquire timeout it *also* proceeds. Two `open-change-request` runs on one repo can then corrupt the shared working tree / `index.lock`. Documented; note that "proceed anyway after timeout" is the surprising half. | `services/change_requests/repo_lock.py` | Fail the step on timeout (raise `RuntimeError`), keep fail-soft only for "Redis unconfigured". | |
| W5 | L | **S15 still open.** `CertificateService.upload` reads the whole upload into memory, no size cap; the app has no global body limit (relies on the reverse proxy). | `services/certificates/certificate_service.py` | Cap at 64 KiB for PEM; document the proxy body limit in `docker/DOCKER.md`. | |
| W6 | L | **Secret redaction is shape-based.** `redact_secrets_in_data` catches sealed envelopes, known bag paths and secret-looking key names, and its docstring is honest that a step which copies an unwrapped secret into a free-text field escapes it. With 52 step packages this is the main residual leak channel into `WorkflowStepResult.output`. | `services/workflow_context/secret_fields.py` | Add a content-based pass: after a run resolves credential values, also replace exact occurrences of those values (≥ 8 chars) in persisted outputs. Cheap and closes the free-text case. | |
| W7 | info | **`verify_ssl=False` clients** for Nautobot/ISE/pyATS and **Netmiko without host-key checking** remain as documented accepted risks in `doc/SECURITY-NOTES.md`. Re-checked; still accurately described. `doc/SECURITY-NOTES.md` still references the deleted `doc/FABLE-ANALYSIS.md` and the old `services/sources/git/git_source_service.py` path. | `doc/SECURITY-NOTES.md` | Update the two stale references. | |

---

## 7. CLAUDE.md compliance

| Standard | Status | Notes |
|---|---|---|
| Model → Repository → Service → Router | ✅ | Guard script passes; every new domain (vault, change requests, webhooks) follows it. `GitWebhookService` and `ChangeRequestService` correctly own the logic; routers are thin. |
| Models one file per domain, exported from `__init__` | ✅ | 20 model classes now. CLAUDE.md still says "15 tables (10 domain + 5 RBAC)" and its key-file list omits `background_tier`, `notifications`, `schedules`, `user_preferences`, `workflow_changes`. |
| Tables have FKs, indexes, timestamps | ✅ | `credentials` vault columns, `change_requests`, `git_repositories.webhook_*` all conform. `GitRepository` is still classic `Column(...)` rather than `Mapped[...]` (source of ~7 pyright false positives). |
| No `text()` outside allow-list; no raw SQL composition | ✅ | guard passes |
| No raw exception text in 5xx | ✅ | guard passes; vault 503s go through `raise_internal_server_error` |
| No f-string logging | ✅ | 0 |
| Thin routers | ✅ | improved: `routers/credentials.py` is a clean delegate; the ISE/Nautobot `ops.py` repetition noted last time is unchanged |
| Pydantic validation at boundaries | ⚠️ | Only 4 of 35 model files use `extra="forbid"` (was 11 models); `CredentialCreate`/`GitRepositoryRequest` silently drop unknown fields; no `max_length` on secret fields (V11, W2) |
| Auth on every endpoint | ✅ | AST-verified: 216 routes, 7 anonymous by design, 6 own-data, 203 permission-gated |
| Rate limiting on all endpoints (global rule) | ❌ | Still only login, change-password and the webhook; and the login limiter itself is broken behind the proxy (T1) |
| Files ≤ 800 lines (global rule) | ⚠️ | `hatchet/workflows/workflow_run.py` and `step_runner.py` were split into packages (done well). One file remains over: `workflow_steps/run_command/executor.py` (1 073) |
| Functions < 50 lines | ⚠️ | unchanged from last audit; the vault package itself is exemplary (largest function 40 lines) |
| Immutability | ✅ | `VaultConfig`, `VaultToken`, `*Secret` result types are frozen dataclasses |
| 80 % coverage, TDD | ✅ | 84 % with ratchet at 81 %; the vault and RBAC policy surfaces have dedicated tests |
| Ruff with `S`/`ASYNC` | ✅ | clean |
| CI: ruff, pyright, pip-audit, guards, tests | ✅ | `.github/workflows/backend-ci.yml`; pyright advisory (158, tracked) |
| Vault config "env-based only, never Settings-KV" (CLAUDE.md) | ✅ | verified |
| Workflow step rules (registry dispatch-only, `git_repository_id` via loader, `ValueError`/`RuntimeError`) | ✅ | spot-checked `open_change_request`, `from_change_request`, `encrypt_attribute` |
| Docs current | ⚠️ | CLAUDE.md: table count, model list, the OIDC-binding claim (T6). `doc/SECURITY-NOTES.md`: two stale paths (W7). `services/auth/auth_service.py` and `login_rate_limiter.py` docstrings still cite the deleted `doc/FABLE-ANALYSIS.md`. |

---

## 8. Python and code-quality notes

- **Done well since last time:** the `StepRunner` and `workflow_run` splits are pure moves with a
  Phase-0 safety-net test commit before them; `CredentialManager` collapses three resolver shapes
  into one typed facade with frozen result dataclasses and a written-down retirement plan for the
  shims; `core/vault.py` mirrors `core/dev_tools.py` as a thin, import-safe enablement module;
  `OpenBaoService` mirrors `NautobotService`'s lifecycle shape so there is one pattern for app-scoped
  clients; `production_guards` stays a pure function with keyword-only parameters, so every new
  check is unit-testable without env manipulation.
- **`except ...: pass` grew from 13 to 18.** `services/git/{service,config,file_service,debug_service,env}.py`
  (13), `redis_cache_service.py` (2), plus new ones in `login_rate_limiter.clear` (Redis delete,
  fine), `run_input_validation.py` and `run_command/executor.py`. The git ones still deserve a
  `logger.debug`.
- **`CredentialsService.__init__` still constructs `EncryptionService` on every instantiation**,
  which is cheap now that the key is `lru_cache`d, but `CredentialManager` constructs a fresh
  `CredentialsService` per call and `GitAuthenticationService.resolve_credentials` opens its own
  `SessionLocal()` outside the caller's unit of work (documented as a shim to retire).
- **`_read_vault_data` swallows the vault `path` into the 503 log only** — good; but
  `CredentialVaultUnavailableError(str(exc))` carries the OpenBao message (`"OpenBao path not
  found: credentials/x-12"`) into the exception text. The routers never surface it, but a future
  router that does `detail=str(exc)` would. Consider a fixed message plus `__cause__`.
- **`RBACRepository.update_role` / `UserRepository.update_user` `**kwargs` + `setattr`** — still
  the mass-assignment shape noted last time; callers are safe today.
- **pyright** at 158 advisory errors; `doc/OPEN_TODOS.md` triages the buckets credibly.

---

## 9. What to do before making the repository public

Ordered by risk, then by effort. Items 1–7 are the ones I would not publish without.

**Blockers**

1. **T1 / W1** — rewrite client-IP resolution (rightmost non-trusted XFF; proxy overwrites the
   header) and make the login limiter per-IP *and* per-username with backoff instead of a hard
   per-username lock. Set `TRUSTED_PROXY_IPS` in compose. Tests for spoofed XFF and for the
   lockout case.
2. **R1** — password reset / username change on a target whose effective permissions exceed the
   actor's requires admin (or make both admin-only). Test with a target holding
   `credentials:reveal` and an actor without it.
3. **R2** — count only active users in `assert_not_last_admin` and `role_has_members`.
4. **V1** — refuse `VAULT_VERIFY_SSL=false` outside development.
5. **V2** — per-operation temp file for vault-backed SSH keys; delete on credential delete/rename.
6. **V3** — destroy all KV versions on delete (`metadata` delete); decide and document version
   retention on update (`max_versions` or `destroy`).
7. **V4** — lease-driven renew interval; re-login + single retry on 403; startup warning on
   lease/period mismatch.

**First hardening pass (1–2 weeks after)**

8. **T2, R3, R6/S14** — `assert_not_self` for password/username changes; P4 on reactivation;
   `owner_user_id` on inventories.
9. **V5–V9** — management client only in the API process; `repr=False`; 403 disambiguation;
   cross-cache invalidate; fail-closed delete.
10. **W2, W3, W5, V11** — input bounds: webhook secret `min_length`, byte-wise `compare_digest`,
    certificate size cap, secret field `max_length`.
11. **S9** — generic per-user rate limiting for the expensive endpoints (Netmiko, ISE, git sync,
    template render), reusing the fixed limiter from item 1.
12. **T3, T4** — make `tv`/`sid_iat` mandatory; validate refresh window ≤ session cap.
13. **V12, V14** — `vault_ok` in `/health/ready`; runbook `secret_id_ttl`.

**Repository hygiene for a public release**

14. Add `SECURITY.md` (how to report a vulnerability, supported versions, the accepted-risk list
    from `doc/SECURITY-NOTES.md` in one paragraph). The repo has `LICENSE` (Apache-2.0) and
    `INSTALL.md` already.
15. Fix the documentation drift: CLAUDE.md table/model count and the OIDC-binding claim (T6);
    `doc/SECURITY-NOTES.md` stale paths; the two `doc/FABLE-ANALYSIS.md` references in
    `auth_service.py` and `login_rate_limiter.py`.
16. `docker/openbao/docker-compose.yaml` ships a fixed dev root token by design — keep it, but make
    sure the file header says "dev mode, in-memory, never expose port 8200" (it does) and that
    `INSTALL.md` links `doc/VAULT_INTEGRATION.md` for the production path.
17. Git history is clean (no `.env`, keys or provider YAML ever committed); no action needed, but
    run `gitleaks` or `trufflehog` once more on the final tree right before flipping visibility.
18. Decide whether `routers/git/debug.py` and `scripts/ise_test*.py` (sandbox passwords under
    `# noqa: S105`) belong in the public tree; moving the scripts to `scripts/manual/` or
    `tests/integration/` avoids a secret-scanner false alarm on day one.

**Backlog**

19. R4, R5, R7, T5, V10, V13, W4, W6; the `run_command` executor split; `extra="forbid"` sweep;
    pyright backlog per `doc/OPEN_TODOS.md`.

---

## 10. Appendix — the route scan

Unauthenticated (by design): `POST /auth/login`, `POST /auth/refresh`, `GET /auth/oidc/providers`,
`GET /auth/oidc/{id}/login`, `POST /auth/oidc/{id}/callback`, `POST /auth/oidc/{id}/logout`,
`POST /webhooks/git/{id}` (HMAC).

Authenticated, no permission (own data): `GET /auth/me`, `POST /auth/change-password`,
`POST /auth/logout`, `GET|PUT /dashboard/layout`, `GET /rbac/users/me/permissions`.

Everything else (203 routes) carries `require_permission(...)` or `require_role(...)` at route or
router level. Dev-only routes (`git/*/debug/*`, `system/schema/migrate`, `system/rbac/seed`,
`oidc/debug`, `oidc/{id}/test-login`) are additionally gated by `ENABLE_DEV_TOOLS`, which
`production_guards` refuses outside development.
