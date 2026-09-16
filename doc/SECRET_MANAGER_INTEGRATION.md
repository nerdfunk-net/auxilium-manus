# Secret Manager Integration (planning)

**Status: design proposal, nothing implemented yet.** This document lays out the
architecture for a new "Secret Manager" domain before any backend/frontend code is
written, per the project's research-and-plan-first workflow.

Operational network secrets — device TACACS+ keys, SNMP community strings/SNMPv3
credentials, and similar per-device or per-team secrets — generated, rotated, and
read back **by workflows at run time**, stored in an external secret manager
(OpenBao or Infisical) chosen per connection.

## Contents

- [Why this is a separate domain from VAULT_INTEGRATION.md](#why-this-is-a-separate-domain-from-vault_integrationmd)
- [Decisions already made](#decisions-already-made)
- [Architecture](#architecture)
- [File map (proposed)](#file-map-proposed)
- [Data model](#data-model)
- [Client abstraction](#client-abstraction)
- [OpenBao client](#openbao-client)
- [Infisical client](#infisical-client)
- [Path / key convention](#path--key-convention)
- [Workflow steps](#workflow-steps)
- [Secret handling in the run engine](#secret-handling-in-the-run-engine)
- [RBAC](#rbac)
- [Fail-closed semantics](#fail-closed-semantics)
- [Open design question: per-field storage shape](#open-design-question-per-field-storage-shape)
- [Configuration](#configuration)
- [Tests (planned)](#tests-planned)
- [Deferred / follow-ups](#deferred--follow-ups)

## Why this is a separate domain from VAULT_INTEGRATION.md

`doc/VAULT_INTEGRATION.md` stores **the app's own credentials** (Nautobot tokens,
git creds, SSH keys) in OpenBao instead of Fernet-encrypted PostgreSQL columns, and
is deliberately **read-only from workflow/runtime code** — the doc states this
explicitly: `vault_writer` (the management OpenBao client) is injected *only* by
`routers/credentials.py`, so "runtime / step code is *structurally* read-only, not
merely policy-restricted." That boundary exists on purpose: a workflow step can
never write to the app-credential vault, only a human can, via the Settings UI.

This feature needs the opposite: a workflow step must **generate and write** a new
secret at run time (rotate a TACACS+ key, then push it to the device). That is a
different, new trust boundary, so it gets its own domain — its own DB table, its own
client/service layer, its own RBAC permissions — rather than extending
`CredentialsService`/`Credential`. The two systems intentionally share nothing except
the underlying OpenBao KV v2 wire protocol code (generalized, not duplicated — see
[OpenBao client](#openbao-client)) and the credential-encryption key used by
`seal_secret`/`unwrap_secret` for in-run handling (see
[Secret handling in the run engine](#secret-handling-in-the-run-engine)).

## Decisions already made

Resolved in discussion before this doc was written — do not re-litigate without a
reason:

- **Both OpenBao and Infisical**, built behind one abstraction, in parallel — not
  one now and one later.
- **Multiple named connections** (DB-backed, `secret_manager_connections` table),
  not a single env-configured backend like `VAULT_*`. Mirrors the `GitRepository`
  consolidation: one config system, admin-managed in Settings, not env/KV.
- **No browse/reveal UI in Manus.** The network team looks at secrets directly in
  Infisical's (or OpenBao's) own UI. Manus only manages connections and exposes
  workflow steps.
- **Generated secrets are pipe-only.** A `secret-generate` step's output value flows
  only to later steps in the same run (e.g. a push-config step); it is never shown
  in the run UI, never persisted in plaintext to `workflow_step_results`, never
  logged.

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
                                     (generalized KV v2 client)   (Universal Auth + secrets API)
```

Each configured connection gets its **own live client instance** with its own auth
session and (for OpenBao) token-renewal loop — this is new infrastructure, not a
reuse of the existing two-singleton `core/vault.py` pattern, because that pattern is
hardcoded to exactly one OpenBao connection read from env vars.
`SecretManagerClientRegistry` is a small `dict[int, SecretManagerClient]` keyed by
`secret_manager_connections.id`, built lazily on first use per connection (mirroring
`CredentialsService`'s lazy `vault_reader` resolution), with an `invalidate(id)` call
from the connection-update/delete router so an edited connection doesn't keep serving
a stale client.

## File map (proposed)

```
backend/services/secret_manager/
  config.py            SecretManagerConnectionConfig (frozen dataclass) — resolved from a DB row
  client.py            SecretManagerClient Protocol (get/set/generate/history/delete)
  openbao_client.py    OpenBaoSecretManagerClient — generalizes services/vault/client.py's
                        KV v2 code, parametrized by mount + path (not hardcoded to
                        "manus" / "credentials/*")
  infisical_client.py  InfisicalSecretManagerClient — Universal Auth + secrets API
  auth.py              Shared VaultTokenManager reused for OpenBao connections;
                        a small InfisicalTokenManager for Universal Auth access tokens
  registry.py          SecretManagerClientRegistry — lazy per-connection client cache
  service.py           SecretManagerService — facade workflow steps call
  policy.py            SecretGenerationPolicy (charset preset + length) + generate()
  exceptions.py        SecretManagerError -> Unavailable / AuthError / NotFound / ConfigError

backend/core/models/secret_manager.py     SecretManagerConnection SQLAlchemy model
backend/models/secret_manager.py          Pydantic request/response models
backend/repositories/secret_manager_repository.py
backend/services/secret_manager/connection_service.py   CRUD for secret_manager_connections
backend/routers/secret_manager.py         connection CRUD + test-connection

backend/workflow_steps/common/secret_manager_connection_loader.py   resolve connection_id -> config
backend/workflow_steps/secret_get/       executor.py, config.py
backend/workflow_steps/secret_set/       executor.py, config.py
backend/workflow_steps/secret_generate/  executor.py, config.py

frontend/src/lib/query-keys.ts            + queryKeys.secretManager.*
frontend/src/components/features/settings/secret-manager/
  components/secret-manager-connections-canvas.tsx
  dialogs/secret-manager-connection-form-dialog.tsx
frontend/src/components/features/workflow-steps/{secret-get,secret-set,secret-generate}/

backend/tests/unit/test_secret_manager_*.py
backend/tests/integration/test_secret_manager_integration.py   opt-in, against live OpenBao + Infisical
```

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
    # Backend-specific fields, not flat columns (see rationale below):
    #   openbao:   {"addr": "...", "mount": "manus-network", "namespace": "..."}
    #   infisical: {"site_url": "...", "project_id": "...", "environment": "prod"}
    backend_config = Column(JSON, nullable=False, default=dict)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_secret_manager_conn_active", "is_active"),
    )
```

**Why `backend_config` is JSON, not flat columns like `GitAuthType`.** `GitAuthType`
variance is narrow (token vs ssh_key vs generic — mostly which credential field to
read). OpenBao needs `addr` + `mount` + optional `namespace`; Infisical needs a site
URL + `project_id` + `environment`. Forcing both into one flat column set means most
columns are `NULL` for one backend or the other, same problem the git-config KV
system had before consolidation. A `backend_config: JSON` validated per-backend at
the Pydantic layer (`OpenBaoConnectionConfig` / `InfisicalConnectionConfig` discriminated
by the `backend` field) avoids that without reintroducing a KV-style config system —
this is still one table, one CRUD path, just like `GitRepository`.

**`credential_name`** resolves this *connection's own* auth material via the
existing `CredentialManager` facade (`CredentialManager.generic(name)` — a
`generic`-type credential holding the OpenBao AppRole `secret_id` or the Infisical
Universal Auth `client_secret` as its password field, username unused or holding the
`role_id`/`client_id`). This reuses the existing credential-resolution seam instead
of inventing a third way to store "a secret needed to reach a secret store."

## Client abstraction

```python
class SecretManagerClient(Protocol):
    def get_secret(self, path: str, *, version: int | None = None) -> dict[str, Any]: ...
    def set_secret(self, path: str, data: dict[str, Any]) -> int | None: ...          # returns new version if known
    def generate_and_store(self, path: str, field: str, policy: SecretGenerationPolicy) -> tuple[int | None, str]: ...
    def get_secret_history(self, path: str) -> list[SecretVersionInfo]: ...            # best-effort; see Infisical caveat
    def delete_secret(self, path: str) -> None: ...
```

`SecretManagerService` (the facade, `services/secret_manager/service.py`) is what
workflow steps actually call:

```python
class SecretManagerService:
    def __init__(self, db: Session) -> None:
        self._connections = SecretManagerConnectionService(db)

    def get_secret(self, connection_id: int, path: str, *, version: int | None = None) -> dict[str, Any]: ...
    def set_secret(self, connection_id: int, path: str, data: dict[str, Any]) -> int | None: ...
    def generate_secret(self, connection_id: int, path: str, field: str, policy: SecretGenerationPolicy) -> tuple[int | None, str]: ...
```

It resolves the connection row via `secret_manager_connection_loader.py` (the
`git_repository_loader.py` analog — raises `ValueError` for missing/inactive
connections, surfaced as a step failure), gets the live client from
`SecretManagerClientRegistry`, and dispatches. No `storage_backend`-style branching
inside this facade — the branching lives entirely inside the registry (which client
class to instantiate) and each client's own implementation.

## OpenBao client

`OpenBaoSecretManagerClient` reuses the existing `services/vault/client.py` KV v2
request/retry/cache/auth machinery (`_request` status mapping, `VaultTokenManager`,
`InProcessTTLCache`) almost unchanged — that code is already fully general KV v2,
just currently instantiated with `mount="manus"` and paths always prefixed
`credentials/`. The only change needed is to stop hardcoding those and instead take
`mount` + a path prefix from the connection's `backend_config`. `get_secret_history`
for OpenBao lists versions via `GET /v1/<mount>/metadata/<path>` (KV v2's metadata
endpoint returns a `versions` map with `created_time`/`destroyed`/`deletion_time` per
version) and `get_secret(path, version=N)` adds `?version=N` to the existing
`read_kv` GET. This is genuinely full version history — same guarantee
`VAULT_INTEGRATION.md` already relies on for credential rotation.

**AppRole role/policy**, new and separate from `manus-app`/`manus-manage`:

```hcl
# manus-network-secrets.hcl — one role covering read+write, since
# workflow steps legitimately need to write (rotate a key) at runtime,
# unlike the read-only manus-app policy.
path "manus-network/data/*"     { capabilities = ["create", "read", "update"] }
path "manus-network/metadata/*" { capabilities = ["read"] }
```

One role per connection (or one shared role if all connections use the same
OpenBao cluster with different mounts) — an ops decision left to the runbook, not
this doc.

## Infisical client

`InfisicalSecretManagerClient` is new. Verified against Infisical's current docs
(2026-09):

- **Auth**: Universal Auth machine identity. `POST /api/v1/auth/universal-auth/login`
  (form-encoded `clientId` + `clientSecret`) → `{accessToken, expiresIn,
  accessTokenMaxTTL, tokenType}`. Renew via `POST
  /api/v1/auth/universal-auth/renew` with the token as a Bearer header. Structurally
  the same shape as OpenBao AppRole, so a small `InfisicalTokenManager` mirroring
  `VaultTokenManager`'s login/renew/invalidate state machine is the right amount of
  reuse (same pattern, separate class — the wire formats differ too much to share
  code, only the state machine shape is common).
- **Secret CRUD**: `POST /api/v4/secrets/{secretName}` (create; body: `projectId`,
  `environment`, `secretValue`, optional `secretPath` default `/`), `GET
  /api/v4/secrets` (list; query: `projectId`, `environment`, `secretPath`). Update
  and delete endpoints exist at parallel paths
  (`PATCH`/`DELETE /api/v4/secrets/{secretName}`) per the same resource shape —
  confirm exact verbs against `https://infisical.com/docs/api-reference` when
  implementing, this doc's research pass did not exhaustively fetch every verb.
- **Version history — verify before relying on it.** Infisical does expose
  `GET /api/v1/secret-versions?secretId=<id>` (full history with `createdAt`) and a
  `version` query param on secret reads. **However, Infisical/infisical#3263 (open
  upstream issue) reports that requesting a specific version via the `version` param
  sometimes returns the latest version instead** — i.e. version-pinned reads may not
  reliably work depending on the deployed Infisical version. Given the "retrieve the
  previous TACACS key" use case depends on this, **do not implement
  `get_secret_history`/`get_secret(version=N)` for the Infisical client without
  first testing it end-to-end against the actual Infisical instance/version this
  deployment will run** (self-hosted or Infisical Cloud). If it doesn't work
  reliably, the honest options are: (a) document that "retrieve previous secret" is
  OpenBao-only for now, or (b) have `secret-set`/`secret-generate` also write a
  parallel timestamped path (`network/{device}/tacacs/history/{iso8601}`) as a
  belt-and-braces history mechanism independent of the backend's native versioning.
  This is a real open item, not a nit — resolve it during implementation, not
  by assumption.

## Path / key convention

Device secrets use a stable, device-scoped path independent of DB names, so it
survives credential/inventory renames:

```
network/{device_key}/tacacs
network/{device_key}/snmp
```

`{device_key}` is templated from device-targeting context available to the step
(e.g. `{device.name}` or a stable inventory identifier — same templating mechanism
`filename_template` already uses in `store-artifact`, reused rather than
reinvented). `path` in a step's config is therefore usually a template string, not
a literal.

## Workflow steps

Three new steps, following `doc/WORKFLOW-STEPS.md`'s package structure
(`backend/workflow_steps/{step_id}/executor.py` + `config.py`, one `step_registry.py`
dispatch entry, one `registry.yaml` entry, a frontend `ConfigPanel`):

| Step | Config | Behaviour |
|---|---|---|
| `secret-get` | `connection_id`, `path` (templated), `field`, optional `version` | Reads and seals the value into the device's attribute bag (see below). Config-error (missing connection/path) → `ValueError`; secret not found is a per-device failure outcome, not a hard raise, matching other per-device steps. |
| `secret-set` | `connection_id`, `path` (templated), `field`, `value_source` (a literal or an attribute-path expression) | Writes an explicit value, e.g. one typed into a static-attribute run input or piped from an upstream step. |
| `secret-generate` | `connection_id`, `path` (templated), `field`, `policy: {charset, length}` | Generates a random value per `SecretGenerationPolicy`, writes it, and seals it into the device's attribute bag for downstream steps (e.g. a push-config step in the same run) — this is the TACACS-rotation primitive. |

`artifact_type: configuration_management` for all three (same category as
`get-device-configs`). `requires: [identity]`, `produces: [secret_manager]` (or per-step
capability names — TBD when the capability graph is designed in detail), `outcomes:
[success, failure]`.

**`SecretGenerationPolicy`** (`services/secret_manager/policy.py`) — a small set of
named presets rather than free-form regex, so the config panel can offer a dropdown:

```python
class SecretCharset(StrEnum):
    HEX = "hex"                 # TACACS+ shared secrets, generic tokens
    ALNUM = "alnum"             # SNMP community strings (avoid symbols some NMS choke on)
    ALNUM_SYMBOLS = "alnum_symbols"   # SNMPv3 auth/priv passphrases (needs length >= 8 per RFC 3414)
```

`generate(policy) -> str` uses `secrets.choice`/`secrets.token_hex` (stdlib
`secrets`, not `random`) — same requirement as any credential-generation code per
the project's security rules.

**Fan-out safety.** `secret-set`/`secret-generate` write to a **per-device-unique**
path (`{device_key}` in the path), so — like `get-device-configs` — they're
fan-out-safe by construction, unlike the shared-working-tree git steps. No fan-in
node required around them.

## Secret handling in the run engine

This reuses the **existing** mechanism in `doc/WORKFLOW-STEPS.md` → "Secret-valued
attributes" (`backend/services/workflow_context/secret_fields.py`) rather than
inventing a new one — that code already solves "a secret must ride in
`DeviceContext.attribute_bags` between steps but never appear as cleartext in
persisted run output":

- `secret-get`/`secret-generate` call `seal_secret(value)` before writing into the
  device's attribute bag (e.g. `secret_manager.tacacs` or a step-configurable bag
  path) — never `set_device_attribute` a raw string.
- The new bag paths get added to `SECRET_BAG_PATHS` in `secret_fields.py` (e.g.
  `("secret_manager", "tacacs")`, or reuse the existing `("tacacs", "shared_secret")`
  path directly if `secret-get`/`secret-generate` write there so downstream steps
  that already read `tacacs.shared_secret` — push-config templates, ISE update
  steps — need no changes at all).
- `redact_secrets_in_data` already fires at every persistence/display boundary
  (`StepRunner._serialize_outcomes`, the fan-out merge path, `log-attributes`), so
  `***REDACTED***` is what lands in `workflow_step_results` — this satisfies the
  "pipe-only, never persisted in plaintext" decision **for free**, with no new
  outcome-level flag needed on `StepOutcome`.
- A downstream step that needs cleartext (a Jinja template building a `tacacs
  key ...` config line) is a **trusted consumer** per the existing contract and
  calls `resolve_device_attribute(..., reveal_secrets=True)` — no new consumer
  category needed if it writes into `tacacs.shared_secret`.
- Per the existing "Known limitation" in `secret_fields.py`: whichever step consumes
  the cleartext must keep it in-memory for that one call only, never copy it into a
  differently-shaped output (a log line, a diff entry). This applies unchanged to
  `secret-generate`'s consumers.

This is the single most important simplification this design makes over a naive
"new mechanism per feature" approach: **no changes to `StepOutcome`, `StepRunner`,
or the persistence layer are needed at all.** The existing seal/redact contract
already covers this use case; only new `SECRET_BAG_PATHS` entries (or reuse of the
existing TACACS one) and three new steps that call `seal_secret`/`unwrap_secret`
correctly are required.

## RBAC

New permission resource `secrets`:

| Permission | Gates |
|---|---|
| `secrets:read` | Including a `secret-get` step in a workflow save; viewing connection config (non-secret fields) in Settings |
| `secrets:write` | Creating/editing/deleting a `secret_manager_connections` row; including `secret-set`/`secret-generate` in a workflow save |

Enforced the same way as every other domain: `Depends(require_permission("secrets",
"write"))` on the connection router; whether a *workflow save* containing a
write-capable step should also be gated by the saving user's `secrets:write`
permission (so a low-privilege user can't design a workflow that rotates secrets
even if someone else runs it) is an open question to resolve during implementation —
note it here so it isn't silently skipped.

## Fail-closed semantics

Same shape as `VAULT_INTEGRATION.md`'s table, per connection:

| Situation | Behaviour |
|---|---|
| Connection inactive or missing | `secret_manager_connection_loader` raises `ValueError` → step config error |
| Backend unreachable at connection startup | Soft-fail, logged at ERROR; first real call raises `SecretManagerUnavailableError` → step failure for the devices on that step |
| Backend goes down mid-run | Same — fails loudly for that step/device, other steps unaffected |
| Auth denied | Same 403-retry-once-then-fail pattern as `OpenBaoService` for the OpenBao client; Infisical client mirrors it (retry once after `renew`/re-login, then raise) |

## Open design question: per-field storage shape

OpenBao KV v2 natively stores a **dict of fields at one path** (e.g.
`network/router1/tacacs = {"key": "...", "rotated_at": "...", "rotated_by": "..."}`
in one KV entry). Infisical's model is **one secret = one key + one value**, grouped
by `secretPath`, not a dict-at-path.

Two ways to reconcile, with a real UX trade-off for the network team's Infisical
browsing (the whole reason Infisical was picked):

1. **JSON-blob normalization** — `secret-set`/`secret-generate` always write one
   Infisical secret per path, whose value is the JSON-encoded field dict. Symmetric
   with OpenBao, simplest client code, but a network engineer browsing Infisical's
   UI sees one opaque JSON blob per device instead of readable `tacacs_key = ...`
   rows — worse for exactly the audience Infisical was chosen for.
2. **Flat-field normalization** — each field becomes its own Infisical secret at
   `{path}/{field}` (e.g. `network/router1/tacacs/key`,
   `network/router1/tacacs/rotated_at`), human-readable in the UI, but breaks
   path/field symmetry with OpenBao (multi-field writes become N Infisical API
   calls instead of one, versioning is per-field not per-path) and the client
   abstraction's `set_secret(path, data: dict)` needs backend-specific fan-out
   logic instead of a 1:1 mapping.

**Recommendation:** option 2 (flat fields) for the Infisical client specifically,
since UI readability was the actual reason to add Infisical support in the first
place — a JSON blob in Infisical's UI defeats that purpose. OpenBao keeps its native
multi-field dict-at-path. Accept the asymmetry; it's internal to each client
implementation and invisible to `SecretManagerService` callers, which always pass
`data: dict[str, Any]` regardless of backend. Flag this for explicit sign-off before
implementation, since it's the one place backend choice changes step *behaviour*
(number of API calls, partial-write failure modes) and not just wire format.

## Configuration

Unlike `VAULT_*`, there is **no top-level env config** for the Secret Manager
feature itself — connections are entirely DB-managed, like `GitRepository`. The only
env-level input is whatever `credential_name` each connection points at (an
ordinary `generic`-type row in the existing `credentials` table, itself optionally
`vault`-backed per `VAULT_INTEGRATION.md` — these two systems compose: the app's own
OpenBao vault can hold the Secret Manager connections' own auth material).

## Tests (planned)

**Unit** (mocked, no live backend needed): `SecretManagerClientRegistry` lazy-build +
invalidate; `OpenBaoSecretManagerClient` KV v2 shaping (reusing the existing
`test_vault_client.py` patterns against a parametrized mount); `InfisicalSecretManagerClient`
login/CRUD wire shaping; `secret-get`/`secret-set`/`secret-generate` executors against
a fake `SecretManagerService`, asserting `seal_secret` is called and no plaintext
reaches the returned `StepOutcome`; `SecretGenerationPolicy.generate()` charset/length
coverage.

**Integration** (opt-in, against live OpenBao **and** live Infisical — the latter is
new, no existing fixture): end-to-end generate → device push → get-previous-version,
against both backends, is the test that actually proves or disproves the Infisical
version-history caveat above. Write this test **first**, before building on the
assumption either way.

## Deferred / follow-ups

- **No browse/reveal UI in Manus** — by decision (see above); revisit only if the
  network team finds Infisical's/OpenBao's own UI insufficient in practice.
- **Cert-auth / mTLS for OpenBao secret-manager connections** — token/AppRole only
  for v1, matching `VAULT_INTEGRATION.md`'s own "Cert class + selection wired,
  login body thin" status.
- **Infisical dynamic secrets / secret rotation leasing features**, if any exist,
  are out of scope — this design only uses static KV-style secrets.
- **Per-workflow-save RBAC gating** for write-capable steps (see RBAC section) —
  needs a decision before implementation, not deferred silently.
- **Redis-backed shared client/token cache** across API + worker processes — v1
  keeps the existing in-process pattern (each process logs in and renews
  independently), same acceptable-for-now status as `VAULT_INTEGRATION.md`'s own
  deferred Redis cache.
- **The flat-field vs JSON-blob Infisical storage shape** — see above, needs
  explicit sign-off, not a silent pick, before implementation starts.
