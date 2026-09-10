# OpenBao (Vault) Integration

Optional external secret storage. A credential in the `credentials` table can
keep its secret material either **local** (Fernet-encrypted PostgreSQL columns —
the default and the only behaviour when OpenBao is not configured) or in
**OpenBao** (HashiCorp Vault fork). The choice is made **per credential** in the
credential-manager UI. Everything is gated on `VAULT_ENABLED`; with it off the
codebase behaves exactly as before.

## Contents

- [Why optional / design goals](#why-optional--design-goals)
- [Architecture](#architecture)
- [File map](#file-map)
- [Data model](#data-model)
- [The resolution seam](#the-resolution-seam)
- [OpenBao client](#openbao-client)
- [Authentication](#authentication)
- [Token lifecycle](#token-lifecycle)
- [Runtime vs management roles](#runtime-vs-management-roles)
- [KV layout](#kv-layout)
- [Caching](#caching)
- [Fail-closed semantics](#fail-closed-semantics)
- [Configuration](#configuration)
- [Ops runbook](#ops-runbook)
- [Local development](#local-development)
- [Tests](#tests)
- [Deferred / follow-ups](#deferred--follow-ups)

## Why optional / design goals

Most home / small-team users will never run a secrets manager; some companies
require one. So:

- **The app MUST run 100% unchanged with no OpenBao configured.** No client is
  constructed, the new columns sit at their defaults, every path is byte-for-byte
  the pre-integration behaviour.
- **Only the credential-manager UI changes.** On add/edit the user picks a
  storage backend. Nothing else in the product surface moves.
- **One resolution seam.** A background workflow step (git, Nautobot, ISE, pyATS,
  SSH, …) that needs a secret asks `CredentialsService`; the service looks at the
  row's `storage_backend` and either Fernet-decrypts locally or reads from
  OpenBao. The three existing resolver modules are unchanged.
- **Fail closed.** A `vault`-backed credential whose OpenBao is unreachable fails
  loudly; `local` credentials keep working; a stale copy is never served.
- **Env-based config only** — like `DATABASE_*` / `SECRET_KEY`. No Settings-KV
  row, no config path read out of OpenBao.

## Architecture

```
credential-manager UI  ──create/update/delete──▶  routers/credentials.py
                                                       │  (management OpenBao client, write-capable)
                                                       ▼
workflow step / git / source ──resolve──▶  CredentialsService  ──storage_backend?──┐
                                                       │  (runtime OpenBao client, read-only)      │
                                                       ▼                                           ▼
                                              core/crypto.EncryptionService              services/vault/OpenBaoService
                                              (local, Fernet)                            (KV v2 over sync httpx)
```

The OpenBao client is **synchronous** (`httpx.Client`). The entire
credential-resolution call graph — SQLAlchemy `Session`, FastAPI `def`
endpoints, worker step code — is synchronous, so a sync client keeps the
dispatch inside `CredentialsService` simple with no sync↔async bridge. The one
async part is the background token-renewal loop, driven from the client's
`startup()`/`shutdown()` in the app lifespan and each Hatchet worker's
`start_all`. This is a deliberate, documented deviation from the "async httpx
everywhere" convention, which targets request-scoped outbound calls from async
routers.

## File map

```
backend/services/vault/
  config.py        VaultConfig (frozen dataclass) + resolved_secret_id()
  client.py        OpenBaoService — sync KV v2 client, startup/shutdown, renew loop
  auth.py          VaultAuthStrategy protocol + AppRoleAuth / CertAuth / TokenAuth + build_auth_strategy
  token_manager.py VaultTokenManager — in-memory token, login / renew-self / invalidate
  cache.py         SecretCache protocol + InProcessTTLCache
  exceptions.py    VaultError -> VaultUnavailableError / VaultAuthError / VaultPermissionError /
                                 VaultSecretNotFoundError / VaultConfigError

backend/core/vault.py        vault_enabled(), build_vault_config(), build_vault_management_config(),
                             start_vault_services() / stop_vault_services()
backend/core/config.py       Settings.vault_* fields + Settings._validate_vault()
backend/core/production_guards.py   validate_non_development_secrets(...) vault checks

backend/core/models/credentials.py        + storage_backend / vault_path / vault_secret_fields
backend/models/credentials.py             + CredentialStorageBackend Literal + pydantic fields
backend/services/credentials/credentials_service.py   storage_backend dispatch
backend/repositories/credentials_repository.py        create_no_commit / update_no_commit / commit / rollback / refresh
backend/routers/credentials.py            with_management writer + GET /credentials/vault/status
backend/service_factory.py                _vault_service / _vault_management_service singletons

frontend/src/lib/query-keys.ts            + queryKeys.credentials.vaultStatus()
frontend/src/components/features/settings/credentials/
  hooks/use-vault-status-query.ts
  components/credential-backend-badge.tsx
  dialogs/credential-form-dialog.tsx       + storage-backend select (shown only when vault enabled)
  components/credentials-table.tsx         + Backend column

backend/tests/unit/test_vault_*.py                       client, auth, config guards, service dispatch, router
backend/tests/integration/test_vault_integration.py      opt-in, against a live OpenBao
```

## Data model

Three columns on `credentials` (String + `Literal`, matching `visibility` — the
startup `AutoSchemaMigration` has no `sqlalchemy.Enum` support):

| Column | Meaning |
|---|---|
| `storage_backend` | `"local"` \| `"vault"`. `NOT NULL DEFAULT 'local'` — applied automatically on the next startup, **no** `APPLY_RISKY_DATABASE_MIGRATION` needed (the column carries both `default=` and `server_default=`). |
| `vault_path` | KV path suffix under the mount, e.g. `credentials/lab-switch-42`. `NULL` for `local`. |
| `vault_secret_fields` | Non-secret CSV of the field names stored in OpenBao (`"password"`, `"token"`, `"ssh_key,ssh_passphrase"`). Lets the list view and the `has_*` booleans render **without** a live OpenBao read (metadata must keep working when OpenBao is down). |

### `vault_path` — derived once, frozen on rename

`vault_path` is `credentials/{sanitised-name}-{id}` (same sanitiser as the SSH
key-file names; the surrogate `id` guarantees uniqueness — a global and a private
credential can share a name). It is derived when the credential is created and
**never rewritten**, because:

- `name` is mutable via `CredentialUpdate`, and git/steps resolve by name — a
  path recomputed from `name` at read time would silently point at nothing after
  a rename, and there is no `list` capability to detect it.
- KV v2 has no rename; a move is read+write+delete. An explicit stored pointer
  decouples the DB name from the physical location and makes the future
  `local ⇄ vault` move a pure DB-op + KV-copy.

After a rename the OpenBao path keeps the original name. The (deferred) move tool
is what would rewrite `vault_path`.

### `username` stays in Postgres

Even for `vault` rows the `username` column is populated normally — it is not a
secret and name-resolution / the list view must not need a KV round-trip. Only
true secrets (`password` / `token` / `ssh_key` / `ssh_passphrase`) go to OpenBao.

## The resolution seam

Consolidation happens **at the decrypt layer, not the public-API layer.** The
three resolver modules —

- `workflow_steps/common/credential_resolver.py` (by name),
- `services/credentials/source_credentials.py` (by id, global-only),
- `services/git/auth.py` (by name + `auth_type`),

— plus every ad-hoc reader (`preview_service`, the reveal endpoint,
`settings_service` Nautobot decrypt) all bottom out at four `CredentialsService`
methods: `get_decrypted_password`, `get_decrypted_ssh_key`,
`get_decrypted_ssh_passphrase`, `get_ssh_key_path`. Those four now check
`storage_backend` and either Fernet-decrypt or call `OpenBaoService.read_kv`. The
resolver modules themselves are untouched.

`CredentialsService.__init__(db, *, vault_reader=None, vault_writer=None)`:

- `vault_reader` is resolved lazily from `service_factory.get_vault_service()`
  the first time a `vault` row is actually touched — so local-only call sites and
  unit tests never import `service_factory`.
- `vault_writer` (the management client) is injected **only** by
  `routers/credentials.py`. Every other construction path
  (`service_factory.build_credentials_service`) omits it, so runtime / step code
  is *structurally* read-only, not merely policy-restricted.

`git/auth.py` re-raises `CredentialVaultUnavailableError` /
`CredentialVaultNotConfiguredError` out of its otherwise-broad `except` so a vault
outage on a git clone fails loudly instead of degrading to "no auth".

## OpenBao client

`OpenBaoService` (`services/vault/client.py`) follows the
`services/nautobot/client.py` structure (`startup()` / `shutdown()` + a pooled
client with an ephemeral fallback) but synchronous. KV v2 REST:

| Method | Call |
|---|---|
| `read_kv(path)` | `GET /v1/<mount>/data/<path>` → `data.data`; consults + fills the TTL cache |
| `write_kv(path, data)` | `POST /v1/<mount>/data/<path>` body `{"data": {...}}`; refreshes the cache entry |
| `delete_kv(path)` | `DELETE /v1/<mount>/data/<path>`; invalidates the cache entry |
| `health()` | `GET /v1/sys/health` (unauthenticated) |

`_request` adds `X-Vault-Token` (from `VaultTokenManager.current()`) and
`X-Vault-Namespace`. Status mapping: `403` → invalidate token + `VaultPermissionError`;
`404` → `VaultSecretNotFoundError`; connect error / sealed / `5xx` →
`VaultUnavailableError`. **Failures are never cached.** TLS uses
`core/ssl_config.create_verified_ssl_context()` (or `VAULT_CACERT`), extended
with the client cert/key when `VAULT_AUTH_METHOD=cert`.

`VAULT_ADDR` is operator config, not request-derived, so the per-request SSRF
guard (`validate_outbound_http_url_async`, and async) is **not** applied; a
one-time scheme/host check in `Settings._validate_vault` is sufficient.

## Authentication

Pluggable strategy (`build_auth_strategy(cfg)` in `services/vault/auth.py`):

| Method | `VAULT_AUTH_METHOD` | Notes |
|---|---|---|
| **AppRole** | `approle` (default) | `POST /v1/auth/approle/login` with `role_id` + `secret_id`. `secret_id` comes from `VAULT_SECRET_ID` or `VAULT_SECRET_ID_FILE` (the manual ops-bootstrap delivery path). **Primary, fully implemented.** |
| **Cert / mTLS** | `cert` | `POST /v1/auth/cert/login`; identity is the TLS client certificate loaded into the client's SSL context. Class + selection are wired; the login body is intentionally thin and can be hardened in a follow-up. |
| **Token** | `token` | Static token, no login call. **Development only** — `build_auth_strategy` refuses it unless `ENV=development`, and `production_guards` refuses it outside development too. Enables the `docker/openbao` dev root-token flow. |

## Token lifecycle

`VaultTokenManager` holds the current token **in memory only** — never a file,
the database, or Redis — so a process restart always re-authenticates.

- Configure the OpenBao role with `token_period` (a **periodic** token has no max
  TTL). `VAULT_TOKEN_PERIOD_SECONDS` (default 3600) mirrors it for the renew
  cadence.
- `OpenBaoService._renew_loop` (async, one per process) wakes every
  `token_period − VAULT_RENEW_BUFFER_SECONDS` and calls
  `POST /v1/auth/token/renew-self`.
- On `403` / expiry the manager drops the token and does a full `login()`.
- A `403` on any KV request also invalidates the token; the next request
  re-logs-in (so recovery after an OpenBao outage doesn't wait for the renew
  loop).
- Each API process and each Hatchet worker logs in independently and runs its own
  renew loop. Set the AppRole `secret_id_num_uses = 0` so re-logins over the
  SecretID's lifetime don't exhaust it.

## Runtime vs management roles

Two OpenBao roles / policies, surfaced as two `OpenBaoService` instances with two
tokens (an OpenBao token is bound to one policy set — one client cannot switch):

| Instance | `service_factory` accessor | Config | Policy | Used by |
|---|---|---|---|---|
| Runtime | `get_vault_service()` | `VAULT_ROLE_ID` / `VAULT_SECRET_ID(_FILE)` | `manus-app`: **read** on `manus/data/credentials/*` only | `CredentialsService` resolution — steps, background jobs, git, the reveal endpoint |
| Management | `get_vault_management_service()` | `VAULT_MANAGE_ROLE_ID` / `VAULT_MANAGE_SECRET_ID(_FILE)`, or `VAULT_MANAGE_TOKEN` in dev | `manus-manage`: create / read / update on `manus/data/credentials/*` + delete on `manus/{delete,metadata}/credentials/*` | only `CredentialsService.create/update/delete_credential`, reached only from `routers/credentials.py` |

When `VAULT_ENABLED` and `ENV != development`, the management role material is
**required** — `production_guards` aborts startup without it (single mode; a
read-only-vault deployment is a deferred option).

**On create of a `vault` credential the backend writes the secret to OpenBao**:
insert the row (flush to get the `id`) → derive `vault_path` → map the provided
secret to KV fields by credential type → `management.write_kv(...)` → persist
`vault_path` + `vault_secret_fields` → commit. Any OpenBao failure rolls back the
row (never a `vault` row without a backing secret). The DB then holds only the
pointer + non-secret metadata.

## KV layout

One KV **v2** mount (`VAULT_KV_MOUNT`, default `manus`), flat, one secret per
credential:

```
manus/credentials/<sanitised-name>-<id>
  token: "..."                     # type = token
  password: "..."                  # type = ssh | tacacs | generic | shared_secret
  ssh_key: "-----BEGIN ..."        # type = ssh_key
  ssh_passphrase: "..."            # type = ssh_key, optional
```

The app always knows the exact path from the DB row; **no `list` capability is
needed or granted.** On update, provided fields are merged into the existing
secret (KV v2 auto-versions); the latest version is always read.

## Caching

`OpenBaoService` holds an in-process `InProcessTTLCache` keyed by KV path, TTL
`VAULT_CACHE_TTL_SECONDS` (default 45, range 30–300). Only successful reads are
cached; `write_kv` refreshes the entry, `delete_kv` invalidates it, a failed read
neither reads nor writes the cache. The runtime and management clients have
**separate** caches, so a management write propagates to runtime resolution
within one TTL — acceptable eventual consistency, documented here.

**Next step — Redis-backed shared cache.** `cache.py` defines a `SecretCache`
Protocol precisely so a Redis implementation slots in behind `OpenBaoService`
with no `CredentialsService` change. Not built yet.

## Fail-closed semantics

| Situation | Behaviour |
|---|---|
| OpenBao not configured (`VAULT_ENABLED` false) | `local` credentials work normally. The UI hides the storage-backend picker. Resolving a `vault` row (shouldn't happen) → `CredentialVaultNotConfiguredError`. |
| OpenBao configured but unreachable at **startup** | App boots (soft-fail; logged at ERROR). The renew loop keeps retrying login. `vault` resolution raises `CredentialVaultUnavailableError`; `local` resolution is unaffected. |
| OpenBao goes down **at runtime** | Same — `vault` resolution fails loudly (workflow step fails, git op fails loudly, `GET /credentials/{id}/password` → 503 with `{message, error_id}`), `local` keeps working. Cached secrets within their TTL still serve; the cache is never consulted on a failed read. |
| Token denied (`403`) | Token invalidated, `VaultPermissionError`, next request re-logs-in. |

## Configuration

All env-based; read in `core/config.py`, structurally validated in
`Settings._validate_vault()`, production-hardened in
`core/production_guards.py`. See `backend/.env.example` for the annotated list.

| Var | Default | Notes |
|---|---|---|
| `VAULT_ENABLED` | `false` | Master switch. |
| `VAULT_ADDR` | — | `https://` required outside development. |
| `VAULT_KV_MOUNT` | `manus` | KV v2 mount name. |
| `VAULT_NAMESPACE` | — | OpenBao Enterprise namespace. |
| `VAULT_AUTH_METHOD` | `approle` | `approle` \| `cert` \| `token` (`token` dev-only). |
| `VAULT_ROLE_ID` / `VAULT_SECRET_ID` / `VAULT_SECRET_ID_FILE` | — | Runtime AppRole. |
| `VAULT_MANAGE_ROLE_ID` / `VAULT_MANAGE_SECRET_ID` / `VAULT_MANAGE_SECRET_ID_FILE` | — | Management AppRole. Required outside dev when enabled. |
| `VAULT_TOKEN` / `VAULT_MANAGE_TOKEN` | — | Dev-only static tokens. |
| `VAULT_CLIENT_CERT` / `VAULT_CLIENT_KEY` | — | Cert-auth material. |
| `VAULT_CACERT` | — | CA bundle for the OpenBao server cert. |
| `VAULT_VERIFY_SSL` | `true` | |
| `VAULT_TOKEN_PERIOD_SECONDS` | `3600` | Mirror of the role's `token_period`. Min 60. |
| `VAULT_RENEW_BUFFER_SECONDS` | `600` | Renew this long before the period ends. Must be `<` the period. |
| `VAULT_TIMEOUT_SECONDS` | `5` | Per-request HTTP timeout. |
| `VAULT_CACHE_TTL_SECONDS` | `45` | In-process secret cache TTL (30–300). |

`GET /api/credentials/vault/status` → `{"enabled": <bool>}` (a pure settings
read, no OpenBao call) drives whether the frontend offers the storage-backend
choice. A live-reachability field is a deferred addition.

## Ops runbook

Manual bootstrap by the container/app admin (no delivery pipeline).

1. **Enable the KV v2 mount**

   ```
   bao secrets enable -path=manus -version=2 kv
   ```

2. **Write the two policies**

   ```hcl
   # manus-app.hcl  — runtime, read-only
   path "manus/data/credentials/*" {
     capabilities = ["read"]
   }
   ```

   ```hcl
   # manus-manage.hcl — credential-manager writes
   path "manus/data/credentials/*" {
     capabilities = ["create", "read", "update", "delete"]
   }
   path "manus/delete/credentials/*"   { capabilities = ["update"] }
   path "manus/metadata/credentials/*" { capabilities = ["read", "delete"] }
   ```

   ```
   bao policy write manus-app    manus-app.hcl
   bao policy write manus-manage manus-manage.hcl
   ```

3. **Enable AppRole and create the two roles** (periodic tokens, CIDR-bound to
   the app subnet, unlimited SecretID uses so redeploys don't exhaust it):

   ```
   bao auth enable approle

   bao write auth/approle/role/manus-app \
     token_policies=manus-app token_period=3600 \
     secret_id_num_uses=0 secret_id_ttl=0 \
     token_bound_cidrs="10.0.0.0/24" secret_id_bound_cidrs="10.0.0.0/24"

   bao write auth/approle/role/manus-manage \
     token_policies=manus-manage token_period=3600 \
     secret_id_num_uses=0 secret_id_ttl=0 \
     token_bound_cidrs="10.0.0.0/24" secret_id_bound_cidrs="10.0.0.0/24"
   ```

4. **Fetch RoleIDs and generate SecretIDs**

   ```
   bao read  auth/approle/role/manus-app/role-id
   bao write -f auth/approle/role/manus-app/secret-id
   bao read  auth/approle/role/manus-manage/role-id
   bao write -f auth/approle/role/manus-manage/secret-id
   ```

   Put the RoleIDs in `VAULT_ROLE_ID` / `VAULT_MANAGE_ROLE_ID`; deliver the
   SecretIDs via `VAULT_SECRET_ID_FILE` / `VAULT_MANAGE_SECRET_ID_FILE` (a
   bind-mounted file or Docker secret).

5. **SecretID rotation.** Routine every **~90 days**, plus immediately on:
   suspected leak / a SecretID appearing in a log or backup, operator
   offboarding, an app host/image rebuild, or OpenBao root/unseal-key rotation.
   Rotation (zero downtime with >1 instance): `bao write -f
   auth/approle/role/<role>/secret-id` → update the SecretID file → restart the
   app → `bao write auth/approle/role/<role>/secret-id-accessor/destroy
   secret_id_accessor=<old>`.

## Local development

**`docker/openbao/README.md`** is the copy-paste quickstart — it starts the dev
container and configures the `manus` mount, both policies, and both AppRoles in
one pasteable block. The short version:

`docker/openbao/docker-compose.yaml` runs OpenBao in dev mode on
`127.0.0.1:8200` with a known root token. Then:

```bash
# backend/.env
VAULT_ENABLED=true
VAULT_ADDR=http://127.0.0.1:8200
VAULT_AUTH_METHOD=token
VAULT_TOKEN=<dev root token>
VAULT_MANAGE_TOKEN=<dev root token>
# ENV=development (so token auth and http:// are allowed)
```

Then run step 1 of the runbook (`bao secrets enable -path=manus -version=2 kv`).
Restart the backend — the logs show the runtime + management `OpenBaoService`
started and a token acquired. The credential form now shows the **Storage
backend** selector.

## Tests

**Unit** (`backend/tests/unit/`, always run, mocked — no OpenBao needed):

| File | Covers |
|---|---|
| `test_vault_client.py` | `OpenBaoService` KV v2 URL/body shaping, `403`/`404`/`5xx`/connect-error mapping, TTL cache hit / refresh / no-cache-on-failure |
| `test_vault_auth_strategy.py` | `build_auth_strategy` selection, `AppRoleAuth.login`, `SecretID`-from-file, `TokenAuth` dev-only guard, `VaultTokenManager` login / renew / 403-fallback / invalidate |
| `test_vault_config_guards.py` | `production_guards` vault checks (https-only, no token outside dev, AppRole + management material required, cert material) |
| `test_credentials_service_vault.py` | `storage_backend` dispatch on a real SQLite `Credential` table: create write-through, rollback on OpenBao failure, `get_decrypted_*` vault branch, fail-closed, `_to_dict` `has_*` from `vault_secret_fields`, `update` backend-change → 422 |
| `test_credentials_router_vault.py` | `GET /credentials/vault/status`, `422` when vault not configured, `503` when OpenBao down, `with_management` writer wiring |

**Integration** (`backend/tests/integration/test_vault_integration.py`, opt-in —
never part of a plain `pytest`). Needs a reachable OpenBao (the `docker/openbao`
dev container is enough) with `VAULT_ADDR` + `VAULT_TOKEN` (a root/privileged
token, used only to bootstrap a scratch mount + policies + AppRoles) in
`backend/.env.test`; `VAULT_KV_MOUNT` overrides the mount name (default
`manus-itest`). Skips cleanly when unset or unreachable (`require_openbao`
fixture). Covers, against the live server: KV write/read/delete wire shapes, the
read-only `manus-app` policy actually blocking writes, `renew-self` and
revoked-token re-login, `CredentialsService` create → resolve (incl. the
workflow-step name path) → delete end to end, and fail-closed with a `local`
credential still resolving.

```bash
cd backend && source ../.venv/bin/activate
python -m pytest tests/integration/test_vault_integration.py --no-cov
```

## Deferred / follow-ups

- **Redis-backed shared secret cache** — `SecretCache` Protocol already in place.
- **`local ⇄ vault` move action** — UI control + `storage_backend` change in
  `update_credential` + KV copy/delete + `vault_path` rewrite. The data model
  already permits it (`storage_backend` on `CredentialUpdate`, explicit
  `vault_path`).
- **Full `CertAuth` (mTLS) implementation** — interface + selection are done.
- **Live reachability in `GET /credentials/vault/status`** (`reachable`,
  `token_expires_at`, last-renew) + a `/health/ready` contribution.
- **Read-only-vault deployment mode** (`VAULT_MANAGEMENT_ENABLED=false`) where
  ops pre-provision secrets and the UI hides the vault write option.
- **Collapsing the three resolver seams into one `CredentialManager` facade** —
  worthwhile cleanup, separate PR, its own regression/test burden. Scoped in
  `doc/refactoring/CREDENTIAL_MANAGER_CONSOLIDATION.md`.
- **SecretID delivery automation** — stays a manual ops bootstrap for now.
