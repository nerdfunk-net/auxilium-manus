# Open TODOs

Running list of known, deliberately-deferred cleanups. Each entry says what the
end state should be and what is currently blocking it, so a future session can
pick it up without re-deriving the context.

---

## Retire the three credential-resolver shim layers

**Added:** 2026-09-10 · **Area:** `backend/services/credentials`, `backend/workflow_steps`

### What we have

`services/credentials/manager.py::CredentialManager` is now the single
implementation of "resolve a credential reference to its secret". The three
historical resolver modules were reimplemented as **thin adapters** over it —
they hold no (or almost no) logic any more, just return-shape and
exception-type translation:

| Shim | Logic left in it | Consumers |
|---|---|---|
| `workflow_steps/common/credential_resolver.py` | dataclass → tuple; remap `CredentialLookupError`/`CredentialUnusableError` → `CredentialReference{NotFound,Invalid}Error` | 8 workflow executors |
| `services/credentials/source_credentials.py` | remap facade errors → `SourceCredentialError` | 5 source-config services + 3 routers (`SourceCredentialError` caught by name in 6 places) |
| `services/git/auth.py::GitAuthenticationService.resolve_credentials` | `GitSecret` → `(username, token, ssh_key_path)`; open/close a `SessionLocal` | `GitService`, `GitConnectionService`, `GitDebugService` |

> Note: `GitAuthenticationService` also owns real git-transport logic
> (`build_auth_url`, `setup_auth_environment`, `normalize_url`). Even after the
> resolve part is gone it stays as the git-transport helper — only its
> `resolve_credentials` method is in scope for removal.

### Original goal

Collapse all three into `CredentialManager` and **delete** `credential_resolver.py`
and `source_credentials.py` entirely, so every caller depends on the one typed
interface. See `doc/refactoring/CREDENTIAL_MANAGER_CONSOLIDATION.md`.

### Why it's deferred — the test burden

The runtime cutover is mechanical, but it drags a large, brittle **test** change:

- ~50 `mock.patch("workflow_steps.<step>.executor.resolve_ssh_credential", return_value=(...))`
  sites across ~8 executor test files, several also asserting on the mock's call
  args. Each becomes a `CredentialManager` patch returning an object with
  `.username` / `.password` (etc.) attributes.
- `test_source_credentials_helper.py`, `test_credential_resolver.py`,
  `test_git_auth_credentials.py` currently patch
  `services.credentials.manager.CredentialsService` *through* the shims; they
  should be rewritten to target `CredentialManager` directly.
- 6 `except SourceCredentialError` catch sites → `except (CredentialLookupError, CredentialUnusableError)`.

### When we revisit

Do it as its own PR, strangler-style, one consumer group at a time
(SSH executors → source-config services), each group green before the next.
Rewrite the affected test mocks in the same commit as each group. Delete each
shim only once its last import is gone. Optionally also absorb the id-keyed
private-then-global SSH read in
`services/network/netmiko/preview_service.py` via a new
`CredentialManager.ssh_by_id(credential_id)`.

---

## Wire Batfish Routing Table/Path Check/ACL Check results into per-device templates

**Added:** 2026-09-15 · **Area:** `backend/workflow_steps/batfish_routing_table`,
`batfish_path_check`, `batfish_acl_check`, `backend/services/workflow_context`

### What we have

Extract Facts, Get OSPF Facts, Get BGP Facts, and Batfish Node/Interface
Properties all write into `DeviceContext.parsed[output_key]`, so their
output is reachable from `route-on-attribute` and `render-jinja-template` via
the shared `parsed.<output_key>` namespace (see
`doc/BATFISH_INTEGRATION.md` "Extract Facts" / "Batfish OSPF Facts" and
`jinja-help-dialog.tsx`'s "Batfish (per-device steps only)" section).

`batfish-routing-table`, `batfish-path-check`, and `batfish-acl-check` do
**not** — each stores its result only as one workflow-level artifact plus a
`WorkflowContext.metadata[f"{node_id}.{output_key}"]` pointer (see
`doc/BATFISH_INTEGRATION.md` "Batfish Routing Table" → "Result storage" for
why: every existing `artifact_service.store()` call site is per-device, and
a routing table/reachability/ACL answer is one table covering every queried
node, not naturally splittable per device). Confirmed by reading all three
executors: none of them ever call `device.model_copy(update={"parsed": ...})`.
This was flagged while fixing the Template Editor's `batfish` preview
variable, which had been (incorrectly) modeling these three steps' output as
if it were already usable in a template — see that doc section's "Bug found
and fixed" writeup and the "Open items" entry right below it.

### Original goal

Let a template (`route-on-attribute` or `render-jinja-template`) reference
Routing Table/Path Check/ACL Check results per device, the same way it can
already reference Extract Facts/OSPF/BGP Facts results.

### Why it's deferred

It's a real design question, not a mechanical fix: these steps run one
Batfish call for potentially many nodes' worth of rows (a routing table) or
a single flow-level answer with no device dimension at all (path/ACL check
against one start/end node pair) — there's no existing precedent in this
codebase for splitting one workflow-level answer back onto N devices'
`.parsed`, unlike the "one call already grouped by node" shape the
combined-facts/property engines rely on (`group_rows_by_node`). Doing this
properly likely means either (a) grouping routing-table rows by `Node` and
writing `parsed[output_key]` per matching device — mirroring
`batfish_properties.py`'s `_enrich_devices`, with the same "devices outcome
replaces the device list" tradeoff already accepted for the other Batfish
steps — or (b) leaving path/ACL check's single flow-level answer as
workflow-metadata-only (there's no per-device dimension to attach it to) and
scoping this to Routing Table alone. Needs a decision on which, and whether
it's worth the design cost, before writing code — explicitly out of scope
for the Template Editor bug fix that surfaced this gap.

### When we revisit

Only if a real workflow needs to branch or render per-device on a routing
table / reachability / ACL result — the run-detail viewer
(`batfish-result-panel.tsx`) and the Template Editor's ad-hoc preview (now
clearly marked preview-only) may be sufficient on their own otherwise. If
picked up: start with Routing Table only (it has a real per-node `Node`
column to group by, unlike Path/ACL Check), reusing
`workflow_steps.common.batfish_properties.group_rows_by_node` and the same
`devices`-outcome-replaces-the-list contract already established for
OSPF/BGP Facts and Node/Interface Properties, so behavior stays consistent
across all Batfish steps rather than introducing a fourth pattern.

---

## Clear the pyright backlog (`types` CI job)

**Added:** 2026-09-12 · **Area:** `backend/` (repo-wide typing)

### What we have

`.github/workflows/backend-ci.yml`'s `types` job runs `pyright` (basic mode)
with `continue-on-error: true` and currently reports **158 errors** (up from
the ~149 noted when the job was added). It's advisory only — it never fails
the workflow or blocks a push.

Spot-checked a representative sample of the findings against the actual code
(not just the pyright output) to separate real risk from noise:

| Bucket | Count (approx.) | Verdict |
|---|---|---|
| `Column[T]` vs plain `T` (`services/git/repository_service.py`, `repositories/base.py`) | ~7 | **False positive.** `core/models/git.py` (and others) use classic `id = Column(Integer, ...)` instead of SQLAlchemy 2.0's `id: Mapped[int] = mapped_column(...)`. Runtime value is a plain `int`/`bool`/`datetime`; pyright sees the class-level descriptor type. |
| `str \| None` params annotated as `str` (`services/git/connection.py::_validate_credentials`/`_build_clone_url`) | ~5 | **Stale annotation, not a bug.** Bodies already null-check (`if not resolved_token: ...`). Trivial fix: widen the annotations. |
| `Argument missing for parameter "credentials"` (`services/nautobot/devices/creation.py`, `interface_workflow.py`) | ~15 | **Real typing gap, not a runtime bug.** `DeviceCreationService.__init__` is typed to take `NautobotService`, but production (`workflow_steps/add_to_nautobot/executor.py:163`) passes a `CredentialsBoundNautobotClient` — an intentional duck-typed adapter (see its own docstring) that injects credentials internally. Works fine at runtime; pyright checks calls against the wrong nominal type because the duck-typing isn't expressed via a `Protocol`. |
| Everything else (dict-vs-Pydantic-model args in `routers/templates.py`/`credentials.py`, enum-vs-str in `dashboard_service.py`/`schedule_service.py`, `redis_cache_service.py` bytes/str mixing, `services/git/file_service.py` GitPython stub gaps, `services/ise/client.py`) | ~130 | **Not yet individually verified.** Likely mostly the same two flavors (stub gaps + loose dict/str typing that Pydantic coerces at the boundary), but unconfirmed case-by-case. |

### Original goal

Get `pyright` clean enough to drop `continue-on-error: true` on the `types`
job, so it starts actually blocking on *new* type regressions instead of
being pure noise today.

### Why it's deferred

Volume (158 findings) and the fact that a chunk of the real fix isn't
"correct the annotation" but "introduce a `Protocol`" (the Nautobot
credentials-bound-client bucket) — small in code size but needs a bit of
design, not a mechanical sweep. Nothing in the sampled buckets is an actual
runtime bug, so there's no urgency.

### When we revisit

1. Widen the `str | None` annotations in `services/git/connection.py` — free, zero-risk.
2. Define a `NautobotRestClient` `Protocol` (`rest_request`/`graphql_query` without the
   `credentials` arg) and type `DeviceCreationService`/`InterfaceManagerService` against
   it instead of the concrete `NautobotService` class — fixes the ~15-error bucket properly.
3. Triage the remaining ~130 findings bucket-by-bucket the same way (verify against
   real code before changing anything — several are likely SQLAlchemy `Mapped[]`
   migration work, which is a bigger, separate lift).
4. Once `pyright` is green, remove `continue-on-error: true` from the `types` job.

---

## Support more OpenBao authentication methods for Secret Manager connections

**Added:** 2026-09-16 · **Area:** `backend/services/secret_manager`, `frontend/.../settings/dialogs/secret-manager-connection-dialog.tsx`

### What we have

`OpenBaoSecretManagerClient._build_vault_config` (`services/secret_manager/openbao_client.py`)
hardcodes `auth_method="approle"` — every Secret Manager connection to
OpenBao authenticates via AppRole (Role ID + Secret ID, stored as the
connection credential's username/password), with no way to choose
`cert` (mTLS) or a dev-only static `token`. This came up when a user asked
which OpenBao auth method the feature needs and how to configure it — see
`doc/SECRET_MANAGER_INTEGRATION.md`'s "OpenBao client" section and the
OpenBao tab of the connection page's Help dialog
(`secret-manager-help-dialog.tsx`), both of which currently document AppRole
only because it's the only one wired up.

The groundwork already exists to add the others cheaply: `OpenBaoSecretManagerClient`
already wraps `services/vault/client.OpenBaoService`/`VaultConfig`, and
`services/vault/auth.py::build_auth_strategy` already implements `AppRoleAuth`,
`CertAuth`, and `TokenAuth` behind one `VaultAuthStrategy` protocol for the
app's own credential vault (`doc/VAULT_INTEGRATION.md`). None of that needs
to be rewritten — it needs to be *reached* from a Secret Manager connection's
config instead of a hardcoded `"approle"`.

### Original goal

Let a Secret Manager OpenBao connection pick an auth method the same way the
app's own vault does: `auth_method` in `backend_config` (`approle` default,
`cert` for mTLS, `token` for dev-only), with the matching extra fields
(`client_cert`/`client_key`/`ca_cert` for cert auth) — surfaced conditionally
in `secret-manager-connection-dialog.tsx` the same way the backend field
already switches between OpenBao/Infisical layouts.

### Why it's deferred

No concrete need yet — AppRole covers the primary machine-to-machine case
and matches `VAULT_INTEGRATION.md`'s own "AppRole is primary, cert is a
first-class swappable alternative" status. Adding the other methods now
would mean new config fields, new connection-service validation, cert file
handling, and new frontend UI without a driving use case.

### When we revisit

If/when someone needs mTLS-based (or dev-only static-token) access for a
Secret Manager OpenBao connection specifically:

1. Add `auth_method` (+ `client_cert`/`client_key`/`ca_cert` for `cert`) to
   the OpenBao `backend_config` shape (`models/secret_manager.py`'s
   `OpenBaoConnectionConfig`, and `connection_service.py`'s
   `_REQUIRED_BACKEND_CONFIG_KEYS`/`_validate_backend_config`).
2. In `_build_vault_config`, read `auth_method` from `backend_config` instead
   of hardcoding `"approle"`, and pass through the cert fields when present —
   `VaultConfig`/`build_auth_strategy` already accept them, no new auth code.
3. Add the conditional fields to `secret-manager-connection-dialog.tsx`
   (mirrors the existing `backend === "openbao"` vs `"infisical"` branch,
   one level deeper: `authMethod === "cert"` within the OpenBao branch).
4. Update the OpenBao tab of `secret-manager-help-dialog.tsx` and
   `doc/SECRET_MANAGER_INTEGRATION.md` to document the new method(s) —
   don't let those two drift from the code again.

