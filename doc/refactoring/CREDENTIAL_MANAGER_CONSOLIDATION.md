# Credential Manager Consolidation

**Status:** done (adapter-kept variant) — 2026-09-10.
**Prereq:** the OpenBao integration (`doc/VAULT_INTEGRATION.md`), merged.

## What shipped

One facade, `backend/services/credentials/manager.py::CredentialManager`, is now
the single implementation of "resolve a credential reference to its secret". It
wraps `CredentialsService` and exposes a typed method per shape:

```python
class CredentialManager:
    def __init__(self, db, *, acting_user_id: int | None = None): ...

    # name-keyed, honours acting_user_id (private-then-global), source="general"
    def ssh(self, name: str) -> SshSecret: ...
    def generic(self, name: str) -> GenericSecret: ...
    def shared_secret(self, name: str) -> SharedSecret: ...

    # id-keyed, global-only (raise on non-global / missing)
    def source_credential(self, credential_id: int) -> dict: ...
    def source_secret(self, credential_id: int) -> SourceSecret: ...

    # name + auth_type, global-only, forgiving (missing -> empty GitSecret),
    # may materialise an ssh key file
    def git(self, repository: dict) -> GitSecret: ...
```

Result objects are frozen dataclasses in `backend/services/credentials/secrets.py`
(`SshSecret`, `GenericSecret`, `SharedSecret`, `SourceSecret`, `GitSecret`) plus
`CredentialLookupError` / `CredentialUnusableError` (both `ValueError`).

Vault dispatch is untouched — every method still bottoms out at the four
`CredentialsService.get_decrypted_* / get_ssh_key_path` methods.

## The three former seams are now thin adapters

They were reimplemented as pure delegation over the facade, keeping each domain's
existing return shape and error taxonomy so no call site changed:

| Module | Adapts | Notes |
|---|---|---|
| `workflow_steps/common/credential_resolver.py` | dataclass -> tuple; `CredentialLookupError`/`CredentialUnusableError` -> `CredentialReference{NotFound,Invalid}Error` | 8 executor call sites |
| `services/credentials/source_credentials.py` | facade errors -> `SourceCredentialError` | 5 source-config services + 3 routers; `SourceCredentialError` caught by name in 6 places |
| `services/git/auth.py::GitAuthenticationService` | `GitSecret` -> `(username, token, ssh_key_path)` | also owns git-transport logic: `build_auth_url`, `setup_auth_environment`, `normalize_url` |

New code should call `CredentialManager` directly (the adapters' docstrings say
so).

## Why the adapters were kept

Full cutover (deleting `credential_resolver.py` and `source_credentials.py`) would
touch ~20 executor/service/router call sites plus ~50 `mock.patch(...)` targets
across ~13 test files, several with call-arg assertions to rewrite — a large,
brittle diff whose only benefit is removing ~130 lines of pure delegation. The
same reasoning that keeps `GitAuthenticationService` as a permanent git adapter
(it also carries transport concerns) applies to the other two: no logic lives in
them any more, so there is nothing to drift.

## Deferred (optional future cleanup)

- Cut the ~20 call sites over to `CredentialManager` directly and delete the two
  workflow/source adapter modules. Strangler, group by group (SSH steps ->
  source-config services); rewrite the affected `mock.patch` targets to
  `services.credentials.manager.CredentialsService` / the `CredentialManager`
  symbol.
- Absorb the id-keyed private-then-global SSH read in
  `services/network/netmiko/preview_service.py` via a new
  `CredentialManager.ssh_by_id(credential_id)`.
- Rewrite `test_credential_resolver.py` / `test_source_credentials_helper.py` /
  `test_git_auth_credentials.py` to target the facade instead of going through
  the adapters (they currently patch `services.credentials.manager.CredentialsService`).

## Tests

- `backend/tests/unit/test_credential_manager.py` — 30 tests, the facade's direct
  coverage (mocked `CredentialsService`).
- The three adapter test files keep passing unchanged in intent; their
  `mock.patch` target moved to `services.credentials.manager.CredentialsService`.
