# Secret Manager Integration

**Status: implemented.** Operational network secrets — device TACACS+ keys,
SNMP community strings/SNMPv3 credentials, and similar per-device or
per-team secrets — generated, rotated, and read back **by workflows at run
time**, stored in an external secret manager (OpenBao or Infisical) chosen
per connection.

## Contents

- [Why this is a separate domain from VAULT_INTEGRATION.md](#why-this-is-a-separate-domain-from-vault_integrationmd)
- [Design decisions](#design-decisions)
- [Architecture](#architecture)
- [File map](#file-map)
- [Data model](#data-model)
- [Client abstraction](#client-abstraction)
- [OpenBao client](#openbao-client)
- [Infisical client](#infisical-client)
- [Path / field convention](#path--field-convention)
- [Workflow steps](#workflow-steps)
- [Secret handling in the run engine](#secret-handling-in-the-run-engine)
- [RBAC](#rbac)
- [Fail-closed semantics](#fail-closed-semantics)
- [Configuration](#configuration)
- [Local development](#local-development)
- [Tests](#tests)
- [Deferred / follow-ups](#deferred--follow-ups)

## Why this is a separate domain from VAULT_INTEGRATION.md

`doc/VAULT_INTEGRATION.md` stores **the app's own credentials** (Nautobot
tokens, git creds, SSH keys) in OpenBao instead of Fernet-encrypted
PostgreSQL columns, and is deliberately **read-only from workflow/runtime
code** — `vault_writer` (the management OpenBao client) is injected *only*
by `routers/credentials.py`, so runtime/step code is *structurally*
read-only, not merely policy-restricted. That boundary exists on purpose: a
workflow step can never write to the app-credential vault, only a human can,
via the Settings UI.

This feature needs the opposite: a workflow step must **generate and write**
a new secret at run time (rotate a TACACS+ key, then push it to the device).
That is a different, new trust boundary, so it has its own domain — its own
DB table, its own client/service layer, its own RBAC permissions — rather
than extending `CredentialsService`/`Credential`. The two systems share only
the underlying OpenBao KV v2 wire-protocol code (generalized, reused
directly — not duplicated, see [OpenBao client](#openbao-client)) and the
credential-encryption key used by `seal_secret`/`unwrap_secret` for in-run
handling (see [Secret handling in the run engine](#secret-handling-in-the-run-engine)).

## Design decisions

- **Both OpenBao and Infisical**, behind one `SecretManagerClient` protocol.
- **Multiple named connections** (DB-backed, `secret_manager_connections`
  table), not a single env-configured backend like `VAULT_*`. Mirrors the
  `GitRepository` consolidation: one config system, admin-managed in
  Settings, not env/KV.
- **No browse/reveal UI in Manus.** The network team looks at secrets
  directly in Infisical's (or OpenBao's) own UI. Manus only manages
  connections and exposes workflow steps.
- **Generated secrets are pipe-only.** A `secret-generate` step's output
  value flows only to later steps in the same run (e.g. a push-config step);
  it is never shown in the run UI, never persisted in plaintext to
  `workflow_step_results`, never logged. Achieved for free by reusing the
  existing sealed-secret mechanism — see
  [Secret handling in the run engine](#secret-handling-in-the-run-engine).
- **Resolved during implementation — per-field storage shape.** The design
  pass flagged a tradeoff between one Infisical secret per path holding a
  JSON blob (symmetric with OpenBao's dict-at-path, but opaque in Infisical's
  UI) versus flat per-field secrets (readable, but asymmetric). The actual
  resolution needed neither compromise: Infisical's own `secretPath` /
  `secretKey` primitives map 1:1 onto our `path` / `field`, so a path with
  several fields becomes several individual Infisical secrets sharing one
  `secretPath` — natural for Infisical's API *and* fully readable in its UI,
  with no string concatenation or JSON encoding involved. OpenBao keeps its
  native multi-field dict-at-path. See
  [Path / field convention](#path--field-convention).

## Architecture

```
Settings → Secret Manager Connections UI  ──CRUD──▶  routers/secret_manager.py
                                                            │
                                                            ▼
                                            SecretManagerConnectionService
                                            (secret_manager_connections table)
                                                            │
workflow step (secret-get/set/generate) ──resolve(conn_id)──▶ SecretManagerService
                                                            │  (facade, like CredentialManager)
                                                            ▼
                                          SecretManagerClientRegistry (lazy, cached per connection id)
                                                     │                        │
                                                     ▼                        ▼
                                     OpenBaoSecretManagerClient   InfisicalSecretManagerClient
                                     (wraps OpenBaoService)       (Universal Auth + secrets API)
```

Each configured connection gets its **own live client instance** — new
infrastructure, not a reuse of the existing two-singleton `core/vault.py`
pattern, because that pattern is hardcoded to exactly one OpenBao connection
read from env vars. `SecretManagerClientRegistry` is a `dict[int,
SecretManagerClient]` keyed by `secret_manager_connections.id`, built lazily
on first use per connection, with an `invalidate(id)` call from the
connection update/delete router so an edited connection doesn't keep serving
a stale client.

## File map

```
backend/services/secret_manager/
  exceptions.py        SecretManagerError -> Config/Auth/Unavailable/Permission
  policy.py             SecretCharset + SecretGenerationPolicy + generate_secret()
  client.py             SecretManagerClient Protocol (field-granular) + SecretVersionInfo
  config.py             SecretManagerConnectionConfig (frozen dataclass) + load_connection_config()
  openbao_client.py     OpenBaoSecretManagerClient — thin adapter wrapping services/vault/client.OpenBaoService
  infisical_client.py   InfisicalSecretManagerClient — Universal Auth + secrets API
                         (also holds the private _InfisicalTokenManager — no separate auth.py;
                         the wire formats differ too much from OpenBao's VaultTokenManager to share code)
  registry.py            SecretManagerClientRegistry — lazy per-connection client cache
  connection_service.py  SecretManagerConnectionService — CRUD for secret_manager_connections
  service.py             SecretManagerService — facade workflow steps call

backend/core/models/secret_manager.py     SecretManagerConnection SQLAlchemy model
backend/models/secret_manager.py          Pydantic request/response models
backend/repositories/secret_manager/secret_manager_connection_repository.py
backend/routers/secret_manager.py         connection CRUD + POST /{id}/test
backend/service_factory.py                get_secret_manager_registry() / stop_secret_manager_services()
backend/main.py, backend/hatchet/worker_services.py   shutdown hook (mirrors stop_vault_services)
backend/services/vault/client.py          generalized: read_kv(path, version=), metadata_kv(path) added

backend/workflow_steps/secret_get/       executor.py, config.py
backend/workflow_steps/secret_set/       executor.py, config.py
backend/workflow_steps/secret_generate/  executor.py, config.py
backend/services/execution/step_registry.py   +3 entries
backend/workflow_steps/registry.yaml          +3 entries (palette_category: secrets)
backend/services/auth/rbac_seed.py            +3 permissions (secret_manager.connections)

frontend/src/lib/query-keys.ts                       + queryKeys.secretManagerConnections
frontend/src/hooks/queries/
  use-secret-manager-connections-query.ts
  use-secret-manager-connections-mutations.ts
frontend/src/components/features/settings/
  components/secret-manager-settings-canvas.tsx      connections table (flat under components/,
  dialogs/secret-manager-connection-dialog.tsx        like git-repositories — no nested subdirectory)
  dialogs/secret-manager-help-dialog.tsx              "Help" button on the canvas — tabbed
                                                       OpenBao/Infisical setup walkthroughs
  types/settings-section.ts, utils/settings-section-params.ts,
  constants/settings-sections.ts, components/settings-section-canvas.tsx
                                                       + "secret-manager" section wiring
frontend/src/components/features/workflow-steps/
  shared/secret-manager-connection-field.tsx          connection_id picker shared by all 3 steps
  secret-get/index.tsx, secret-set/index.tsx, secret-generate/index.tsx
frontend/src/lib/plugin-ui-registry.ts                +3 entries
frontend/src/components/features/workflows/utils/step-visuals.ts
                                                       "secrets" palette category (icons, colors,
                                                       order — positioned right below "notify")

backend/tests/unit/
  test_secret_manager_policy.py
  test_secret_manager_connection_service.py
  test_secret_get_executor.py
  test_secret_set_executor.py
  test_secret_generate_executor.py

docker/infisical/   local dev stack (Postgres + Redis + Infisical), mirrors docker/openbao —
                    see "Local development" below
```

**No `workflow_steps/common/secret_manager_connection_loader.py` exists** —
unlike git (where ~10 steps share `git_repository_loader.py`), only three
steps use a connection, and they each instantiate `SecretManagerService(db)`
directly; a shared loader would be a needless indirection for three callers.

**Category reorg (post-initial-implementation):** `encrypt-attribute` and
`decrypt-attribute` were moved from `palette_category: attributes` to
`palette_category: secrets` — they operate on secret-shaped values too, so
they now sit in the same canvas palette group as `secret-get`/`secret-set`/
`secret-generate`. The `secrets` category itself was positioned directly
below `notify` in `ARTIFACT_TYPE_ORDER` (`step-visuals.ts`).

## Data model

```python
class SecretManagerConnection(Base):
    __tablename__ = "secret_manager_connections"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)
    backend = Column(String(50), nullable=False)          # "openbao" | "infisical"
    credential_name = Column(String(255))                  # this connection's OWN auth material
    verify_ssl = Column(Boolean, nullable=False, default=True)
    is_active = Column(Boolean, nullable=False, default=True)
    backend_config = Column(JSON, nullable=False, default=dict)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (Index("idx_secret_manager_conn_active", "is_active"),)
```

`backend_config` shapes (validated in `SecretManagerConnectionService`, not
at the Pydantic-request layer — matching how `GitRepositoryService`
validates business rules):

```
openbao:   {"addr": "...", "mount": "manus-network", "namespace": "..."}   # namespace optional
infisical: {"site_url": "...", "project_id": "...", "environment": "prod"}
```

**Why JSON, not flat columns like `GitAuthType`.** `GitAuthType` variance is
narrow. OpenBao needs `addr` + `mount` (+ optional `namespace`); Infisical
needs a site URL + `project_id` + `environment`. Forcing both into one flat
column set means most columns are `NULL` for one backend or the other — the
same problem the pre-consolidation git-config KV system had.

**`credential_name`** resolves this *connection's own* auth material via the
existing `CredentialManager` facade — `CredentialManager(db).generic(name)`,
a `generic`-type credential holding the OpenBao AppRole `secret_id` /
Infisical `client_secret` as its password field, and `role_id`/`client_id`
as its username. Reuses the existing credential-resolution seam (global-only,
background/system-scoped — no `acting_user_id`) instead of inventing a third
way to store "a secret needed to reach a secret store."

## Client abstraction

```python
class SecretManagerClient(Protocol):
    async def ensure_started(self) -> None: ...   # OpenBao's token-renew loop; no-op for Infisical
    def get_field(self, path: str, field: str, *, version: int | None = None) -> str | None: ...
    def set_field(self, path: str, field: str, value: str) -> int | None: ...
    def delete_field(self, path: str, field: str) -> None: ...
    def get_field_history(self, path: str, field: str) -> list[SecretVersionInfo]: ...
    async def shutdown(self) -> None: ...
```

**Field-granular, not whole-dict-per-path** — a deliberate simplification
over the original design sketch. The three consumers (`secret-get`/
`secret-set`/`secret-generate` executors) always operate on one field at one
path at a time, so a field-granular protocol maps directly onto what callers
need; each backend maps that onto its own native storage shape internally
(OpenBao: read-modify-write the whole dict at `path`; Infisical: one secret
per field, sharing `path` as `secretPath`).

`SecretManagerService` (`services/secret_manager/service.py`) is what
workflow steps actually call — `get_field`, `set_field`, `generate_field`
(generates via `services.secret_manager.policy.generate_secret`, then calls
`set_field`, returning `(version, value)`), and `get_field_history`. All
four are `async def`: resolving a connection's live client
(`SecretManagerClientRegistry.get_or_create`) may need OpenBao's async
`startup()`; once resolved, the field read/write calls themselves are
synchronous HTTP, matching `CredentialsService`'s own "deliberately
synchronous" OpenBao calls. No `storage_backend`-style branching lives in
the facade — which client class to use is decided entirely inside the
registry.

## OpenBao client

`OpenBaoSecretManagerClient` **wraps `services/vault/client.OpenBaoService`
directly** rather than reimplementing KV v2 — that client already takes
`mount`/`addr` per instance via `VaultConfig`, so no wire-protocol
generalization was actually needed beyond two small additions to the shared
client itself (used by this domain, harmless to the existing credential-vault
callers):

- `read_kv(path, *, version=None)` — a pinned version bypasses the
  in-process TTL cache entirely (the cache only ever holds "latest").
- `metadata_kv(path)` — `GET /v1/<mount>/metadata/<path>`, returning the KV
  v2 `versions` map (`created_time`/`destroyed` per version), consumed by
  `get_field_history`.

`get_field`/`set_field`/`delete_field` read-modify-write the whole dict at
`path` (get, mutate one key, `write_kv`) since OpenBao KV v2 has no
per-field write. `get_field_history` ignores its `field` argument — OpenBao
versions the whole dict at a path, not individual fields.

**AppRole role/policy**, new and separate from `manus-app`/`manus-manage`
(one role can cover read+write per connection, since workflow steps
legitimately need to write at runtime, unlike the read-only `manus-app`
policy):

```hcl
path "manus-network/data/*"     { capabilities = ["create", "read", "update"] }
path "manus-network/metadata/*" { capabilities = ["read"] }
```

## Infisical client

`InfisicalSecretManagerClient` (`services/secret_manager/infisical_client.py`)
is new, including a private `_InfisicalTokenManager` in the same file (no
separate `auth.py` — the wire formats differ too much from OpenBao's
`VaultTokenManager` to share code, only the login/re-login *shape* is
common).

- **Auth**: Universal Auth machine identity. `POST
  /api/v1/auth/universal-auth/login` (form-encoded `clientId` +
  `clientSecret`) → `{accessToken, expiresIn, ...}`. **No background renew
  loop** — a deliberate v1 simplification, since Infisical's default
  access-token TTL (7200s) is generous; `_InfisicalTokenManager.current()`
  just re-logs-in lazily once the tracked deadline passes. On a `401`/`403`
  the client invalidates the token and retries the same request once
  (mirrors `OpenBaoService`'s 403-retry-once pattern).
- **Secret CRUD**: `GET`/`POST`/`PATCH`/`DELETE /api/v4/secrets/{secretKey}`
  with `projectId`, `environment`, `secretPath` — `set_field` does a `GET`
  first to decide create vs. update (simpler and more robust than parsing
  error codes from a failed create-on-conflict).
- **Path/field mapping**: our `path` is Infisical's `secretPath` (a folder);
  our `field` is Infisical's `secretKey` (an individual secret name) — see
  [Design decisions](#design-decisions) for why this needed no blob/flatten
  compromise.
- **Version history — unverified, logs a warning.** `get_field_history`
  returns an empty list and logs a warning rather than guessing at an
  implementation: Infisical/infisical#3263 (open upstream issue) reports
  that version-pinned reads sometimes silently return the latest version
  instead. `get_field(..., version=N)` still forwards the `version` query
  param (so the plumbing exists end-to-end) but also logs a warning when
  used. **Do not build a "retrieve the previous TACACS key" workflow on
  Infisical without testing this against the real deployed instance first**
  — `docker/infisical/` (see [Local development](#local-development)) makes
  that test possible locally.
- **Verify before relying on it in production**: the exact `PATCH`/`DELETE`
  verb shapes were not exhaustively cross-checked against every Infisical
  API version during implementation — confirm against
  `https://infisical.com/docs/api-reference` for the specific
  self-hosted/cloud version in use.

## Path / field convention

Device secrets use a stable, device-scoped path independent of DB names, so
they survive credential/inventory renames. All three steps default to:

```
network/{device.name}/tacacs      (field: key)
```

`path_template` is rendered per device via
`services.workflow_context.device_template.render_device_template` — the
same placeholder engine `store-artifact`'s `filename_template` already uses
(`{device.*}`, `{nautobot.*}`, `{git.*}`), including its `strict_templates`
toggle (also exposed on all three steps' config).

## Workflow steps

Three steps, `palette_category: secrets`, `artifact_type:
configuration_management`, `requires: [identity]`, `produces: [attributes]`,
`outcomes: [success, failure]`:

| Step | Config (`workflow_steps/{step}/config.py` defaults) | Behaviour |
|---|---|---|
| `secret-get` | `connection_id`, `path_template`, `field`, `destination_path`, `version` (optional) | Reads and seals the value into the device's attribute bag. A missing value routes that device to `failure` (proceed-with-survivors); a connection-wide error (unreachable/auth-denied) fails the whole step. |
| `secret-set` | `connection_id`, `path_template`, `field`, `mode` (`fixed`\|`attribute`), `fixed_value`, `source_path`, `destination_path` | Writes an explicit value — a literal, or one read from another attribute path (`attribute` mode is a trusted, `reveal_secrets=True` consumer, same as `update-ise-tacacs-key`). Also seals the written value into `destination_path`. |
| `secret-generate` | `connection_id`, `path_template`, `field`, `destination_path`, `charset` (`hex`\|`alnum`\|`alnum_symbols`), `length` | Generates via `secrets.token_hex`/`secrets.choice` (stdlib `secrets`, never `random`), stores it, seals it into `destination_path`. No per-device `failure` outcome exists here — generation can't fail per-device, only the whole-step connection-error path uses `failure`. |

All three default `destination_path` to `tacacs.shared_secret` — the same
bag path `get-ise-tacacs-key`/`update-ise-tacacs-key` already use, so a
downstream Jinja template or ISE-update step written before this feature
existed needs zero changes to consume a secret-manager-sourced value.

**`SecretGenerationPolicy`** (`services/secret_manager/policy.py`) — named
presets, not free-form regex, so the config panel offers a fixed dropdown:
`hex` (TACACS+ keys, generic tokens), `alnum` (SNMP community strings —
avoids symbols some NMS choke on), `alnum_symbols` (SNMPv3 auth/priv
passphrases). Length is bounded 4–256.

**Fan-out safety.** `secret-set`/`secret-generate` write to a
**per-device-unique** path (`{device.name}` in the template by default), so
— like `get-device-configs` — they're fan-out-safe by construction. No fan-in
node required around them.

**Not part of this subsystem: `generate-password`.** `generate-password`
(`workflow_steps/generate_password/`) is a superficially similar step — it
also generates a per-device value and seals it into the device's attribute
bag — but it has no `connection_id`, makes no call into
`SecretManagerService`, and needs no Secret Manager connection at all. It is
pure local generation (`workflow_steps/generate_password/password_policy.py`,
deliberately not under `services/secret_manager/`). See `doc/WORKFLOW-STEPS.md`.

## Secret handling in the run engine

Reuses the **existing** mechanism in `doc/WORKFLOW-STEPS.md` → "Secret-valued
attributes" (`backend/services/workflow_context/secret_fields.py`) rather
than inventing a new one:

- `secret-get`/`secret-set`/`secret-generate` call `seal_secret(value)`
  before writing into the device's attribute bag via
  `workflow_steps.common.attribute_write.set_device_attribute` — never a raw
  string.
- **No new `SECRET_BAG_PATHS` entries were added.** `destination_path` is a
  free-form config field (any `bag.field` path an operator chooses), not a
  fixed set of known paths — so this relies entirely on
  `redact_secrets_in_data`'s *second* mechanism ("any sealed envelope found
  anywhere in the structure is redacted, not just at `SECRET_BAG_PATHS`
  leaves"), which is path-agnostic by design. `SECRET_BAG_PATHS` itself
  exists only to catch *legacy unsealed* cleartext at known paths — since
  these three steps always seal, they don't need an entry there.
- `redact_secrets_in_data` already fires at every persistence/display
  boundary (`StepRunner._serialize_outcomes`, the fan-out merge path,
  `log-attributes`), so `***REDACTED***` is what lands in
  `workflow_step_results` — satisfying "pipe-only, never persisted in
  plaintext" for free, with no changes to `StepOutcome`, `StepRunner`, or
  the persistence layer.
- A downstream step that needs cleartext (a Jinja template building a
  `tacacs key ...` config line) is a trusted consumer per the existing
  contract (`reveal_secrets=True`) — no new consumer category was added.

## RBAC

Permission resource `secret_manager.connections` (matching the codebase's
`resource.subresource` convention, e.g. `sources.nautobot`):

| Permission | Gates |
|---|---|
| `secret_manager.connections:read` | Viewing connections in Settings → Secret Manager |
| `secret_manager.connections:write` | Creating/editing a connection; `POST /{id}/test` |
| `secret_manager.connections:delete` | Deleting a connection |

**Still deferred, not implemented**: gating *which workflows* may include a
write-capable step (`secret-set`/`secret-generate`) by the saving user's own
permissions. No other step in the codebase is gated this way today (workflow
save/run permissions are `workflows:write`/`workflows:execute`, undifferentiated
by step content), so this would be new machinery — noted here so it isn't
silently forgotten, not because it's scheduled.

## Fail-closed semantics

| Situation | Behaviour |
|---|---|
| Connection inactive or missing | `load_connection_config` raises `ValueError` → step config error |
| Backend unreachable / auth denied | `SecretManagerUnavailableError`/`SecretManagerAuthError`/`SecretManagerPermissionError` → the whole step's `failure` outcome (all devices), not per-device — matches `get-ise-tacacs-key`'s "lost connection" handling |
| Field not found | `get_field` returns `None`, not an exception — a per-device `failure`, proceed-with-survivors |

## Configuration

No top-level env config for this feature — connections are entirely
DB-managed, like `GitRepository`. The only env-level input is whatever
`credential_name` each connection points at (an ordinary `generic`-type row
in the existing `credentials` table, itself optionally `vault`-backed per
`VAULT_INTEGRATION.md` — the two systems compose).

## Local development

`docker/infisical/` — a local Infisical stack (Postgres + Redis + the
Infisical app image), mirroring `docker/openbao`'s existing pattern:

```bash
cd docker/infisical
cp .env.example .env
# fill ENCRYPTION_KEY (openssl rand -hex 16), AUTH_SECRET (openssl rand -base64 32),
# POSTGRES_PASSWORD
docker compose up -d
```

Published on `127.0.0.1:8081` (Nautobot's dev stack already uses 8080).
First run: open `http://localhost:8081`, create the instance admin account,
create a project + a Universal Auth machine identity, put its client
id/secret into a `generic` Manus credential, then add a Secret Manager
connection (`backend: infisical`) pointing at it. See the compose file's
header comments for the full reachability/backup notes (container DNS vs.
host-native backend, `ALLOW_LOOPBACK_SOURCE_URLS`, `ENCRYPTION_KEY` backup
requirements).

This stack is what makes it possible to actually test the Infisical
version-history caveat above, rather than continuing to guess at it.

## Tests

**Unit** (`backend/tests/unit/`, mocked, always run):

| File | Covers |
|---|---|
| `test_secret_manager_policy.py` | `SecretGenerationPolicy` length bounds, charset output shape/length, non-determinism |
| `test_secret_manager_connection_service.py` | CRUD against in-memory SQLite, `backend_config` validation per backend, duplicate-name rejection |
| `test_secret_get_executor.py` | config errors, sealed-value-on-found, per-device failure on miss, whole-step failure on `SecretManagerError` |
| `test_secret_set_executor.py` | fixed vs. attribute mode, sealed-source read, unresolved-source per-device failure, connection-error whole-step failure |
| `test_secret_generate_executor.py` | charset/length config errors, generated value sealed + **never appears in metadata** (asserted via `json.dumps` scan), connection-error whole-step failure |

**Known gap, not yet covered**: `openbao_client.py`'s field-merge logic,
`infisical_client.py`'s wire shaping (create-vs-update, token login/retry),
`registry.py`, `service.py`, and `routers/secret_manager.py` have no direct
unit tests yet — the design doc's own guidance was "write the Infisical
integration test first, don't assume," and that remains true; a mocked unit
test of `infisical_client.py`'s HTTP shaping would still be worth adding
before the opt-in integration test against `docker/infisical/`.

**Integration** (opt-in, against live OpenBao *and* live Infisical): not yet
written. `docker/infisical/` now exists to support this — see [Local
development](#local-development).

## Deferred / follow-ups

- **No browse/reveal UI in Manus** — by decision; revisit only if the
  network team finds Infisical's/OpenBao's own UI insufficient in practice.
- **Cert-auth / mTLS for OpenBao secret-manager connections** — AppRole
  only, matching `VAULT_INTEGRATION.md`'s own status for that method.
- **Infisical dynamic secrets / rotation-leasing features**, if any exist,
  are out of scope — this integration only uses static KV-style secrets.
- **Per-workflow-save RBAC gating** for write-capable steps — see
  [RBAC](#rbac); needs a real decision, not silent deferral.
- **Unit tests for the OpenBao/Infisical adapter wire logic and the
  connections router** — see [Tests](#tests).
- **The Infisical version-history caveat** — verify `get_field_history`/
  version-pinned `get_field` against a real Infisical instance
  (`docker/infisical/` makes this possible now) before any workflow relies
  on "retrieve the previous secret" for Infisical-backed connections.
- **Redis-backed shared client/token cache** across API + worker processes
  — v1 keeps the existing in-process pattern, same acceptable-for-now status
  as `VAULT_INTEGRATION.md`'s own deferred Redis cache.
