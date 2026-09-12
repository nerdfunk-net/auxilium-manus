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
