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
