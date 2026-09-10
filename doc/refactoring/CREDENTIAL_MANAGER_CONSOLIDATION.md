# Credential Manager Consolidation

**Status:** not started — scoping note for a future planning session.
**Prereq:** the OpenBao integration (`doc/VAULT_INTEGRATION.md`) is merged. This
builds on it.

## Goal

Today three parallel "resolve a credential to its secret" modules exist, each
with its own signature, lookup key, visibility rule, and return shape. Collapse
their **public API** into one `CredentialManager` facade so callers depend on a
single, typed interface.

## Important: what is NOT in scope

The `storage_backend` dispatch (local Fernet vs OpenBao) is **already**
consolidated — it lives inside four `CredentialsService` methods
(`get_decrypted_password`, `get_decrypted_ssh_key`,
`get_decrypted_ssh_passphrase`, `get_ssh_key_path`) and every seam bottoms out
there. This refactor does **not** touch vault dispatch. It is purely an
API-surface cleanup on top of `CredentialsService`.

## Current state — the three seams

| Seam | Entrypoints | Lookup key | Visibility scope | Returns | Consumers |
|---|---|---|---|---|---|
| Workflow-step resolver — `backend/workflow_steps/common/credential_resolver.py` | `resolve_ssh_credential(db, ref, *, acting_user_id)`, `resolve_generic_credential(...)`, `resolve_shared_secret_credential(...)` | **name** (`credential_reference`, `source="general"`) | global **+ acting user's private** (private wins) | `(username, password)` or `(algorithm, passphrase)` | SSH steps: `get_device_configs`, `login_successful`, `run_command`, `deploy_rendered_template`, `upload_config`; `add_pyats_testbed`; `encrypt_attribute`; `decrypt_attribute` |
| Source-integration resolver — `backend/services/credentials/source_credentials.py` | `assert_global_credential(db, credential_id)`, `resolve_global_secret(db, credential_id)` | **id** (`credential_id`) | **global only** (raises otherwise) | `dict` / `(username, password)` | `ISESourceConfigService`, `PyATSSourceConfigService`, `MattermostSourceConfigService` (`backend/services/<svc>/source_config_service.py`); `SettingsService.get_source_config` (Nautobot token); `backend/services/sources/nautobot/connection.py` |
| Git resolver — `backend/services/git/auth.py::GitAuthenticationService` | `resolve_credentials(repository: dict)` (+ `setup_auth_environment` ctx mgr) | **name** (`repository["credential_name"]`) + `auth_type` (`token`/`ssh_key`/`generic`) | **global only** (`acting_user_id=None`, deliberate) | `(username, token, ssh_key_path)` | `GitService` (clone/pull/push/sync — 4 call sites), `GitConnectionService`, `GitDebugService`; workflow git steps via `workflow_steps/common/git_repository_loader.py` |

**Ad-hoc readers that also call `CredentialsService` directly** (not a "seam" but
in the same blast radius): `backend/routers/credentials.py` (reveal endpoint),
`backend/services/network/netmiko/preview_service.py` (template-editor preview),
`backend/services/settings/settings_service.py` (Nautobot decrypt),
`backend/services/templates/templates_service.py` (visibility check only, no
decrypt).

**Reference validator (no secret read, leave alone):**
`backend/services/execution/reference_resolver.py::_CredentialReferenceResolver`
(`kind="credential"`) — used by schedule-save and `scheduled_trigger.dispatch`.

## Why it's non-trivial

1. **Lookup key differs** — name vs integer id. `credential_resolver` also
   understands an `id`-based `credential:<n>` reference form (used by
   `netmiko/preview_service.py`).
2. **Visibility rule differs on purpose** — the workflow-step seam resolves the
   acting user's *private* credentials (falling back to global); the git and
   source seams are *global-only* by design (background jobs, no acting user). A
   unified API must keep that distinction, not paper over it.
3. **Return shape differs** — `(username, password)` vs `(algorithm, passphrase)`
   vs `(username, token, ssh_key_path)`. The git one materialises an SSH key file
   on disk.
4. **Scope** — ~20 executor call sites plus the git service (4), the three
   source-config services, `SettingsService`, and a handful of routers.
5. **Background context** — executors get `db` via
   `sqlalchemy.orm.object_session(run)` and `acting_user_id = run.triggered_by_id`
   (`None` for scheduled/system runs → global-only). The facade must not change
   that plumbing.

## Sketch of the target

A `CredentialManager` (probably `backend/services/credentials/manager.py`) that
wraps `CredentialsService` and exposes typed methods rather than a single stringly
`get()`. Candidate surface:

```python
class CredentialManager:
    def __init__(self, db, *, acting_user_id: int | None = None): ...

    # name-keyed, honours acting_user_id (private-then-global)
    def ssh(self, name_or_ref: str) -> SshSecret: ...          # (username, password)
    def generic(self, name_or_ref: str) -> GenericSecret: ...
    def shared_secret(self, name_or_ref: str) -> SharedSecret: ...  # (algorithm, passphrase)

    # id-keyed, global-only (raises on non-global)
    def source_secret(self, credential_id: int) -> SourceSecret: ...

    # git: name + auth_type, global-only, may write an ssh key file
    def git(self, repository: dict) -> GitSecret: ...
```

`SshSecret` / `GenericSecret` / … are small frozen dataclasses so callers stop
unpacking bare tuples. Old `resolve_*` functions become thin shims that delegate,
then get deleted call-site by call-site.

## Open questions for the planning session

- One class with typed methods (above) vs a single `get(request)` with a
  discriminated-union request object? The former is less clever and easier to
  migrate incrementally.
- Does `git/auth.py`'s `setup_auth_environment` context manager (URL building,
  `GIT_SSH_COMMAND` wiring) stay in the git service, with only the *resolve* part
  moving to the facade? (Recommended — it's git-transport logic, not credential
  logic.)
- Keep `assert_global_credential` as a separate guard, or fold "must be global"
  into `source_secret()` and drop the standalone function?
- Migration: big-bang vs strangler (shims + per-consumer cutover). Given the
  call-site count, strangler.
- Test strategy: the existing `test_credential_resolver.py`,
  `test_source_credentials_helper.py`, `test_git_auth_credentials.py` should keep
  passing through the shims, then be rewritten against the facade.

## Suggested phasing

1. Land `CredentialManager` + the typed result dataclasses; unit-test it directly
   (mock `CredentialsService`).
2. Reimplement the three `resolve_*` modules and `GitAuthenticationService`'s
   resolve path as shims over the facade — no call-site changes yet, full suite
   green.
3. Cut over consumers group by group (SSH steps → source-config services → git),
   deleting each shim once its last caller moves.
4. Delete `source_credentials.py` / `credential_resolver.py` if fully absorbed;
   update `doc/VAULT_INTEGRATION.md` "The resolution seam" section.
