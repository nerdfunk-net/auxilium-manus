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
with `continue-on-error: true` and reported **158 errors** when this entry was written (since reduced to
54 — see "Bring `pyright` to zero" below, which supersedes the numbers here). It's advisory only — it never fails
the workflow or blocks a push.

Spot-checked a representative sample of the findings against the actual code
(not just the pyright output) to separate real risk from noise:

| Bucket | Count (approx.) | Verdict |
|---|---|---|
| `Column[T]` vs plain `T` (`services/git/repository_service.py`, `repositories/base.py`) | ~7 | **False positive.** `core/models/git.py` (and others) use classic `id = Column(Integer, ...)` instead of SQLAlchemy 2.0's `id: Mapped[int] = mapped_column(...)`. Runtime value is a plain `int`/`bool`/`datetime`; pyright sees the class-level descriptor type. |
| `str \| None` params annotated as `str` (`services/git/connection.py::_validate_credentials`/`_build_clone_url`) | ~5 | **Stale annotation, not a bug.** Bodies already null-check (`if not resolved_token: ...`). Trivial fix: widen the annotations. |
| `Argument missing for parameter "credentials"` (`services/nautobot/devices/*`, managers, resolvers) | ~61 | **Fixed (2026-10).** The resolvers, managers and device services are now typed against the `NautobotApi` protocol (`services/nautobot/api_protocol.py`), which `CredentialsBoundNautobotClient` satisfies; no casts remain. |
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
in `secret-manager-connection-dialog.tsx`.

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
   the OpenBao `backend_config` shape (documented in the
   `backend_config` field description of `models/secret_manager.py`, and `connection_service.py`'s
   `_REQUIRED_BACKEND_CONFIG_KEYS`/`_validate_backend_config`).
2. In `_build_vault_config`, read `auth_method` from `backend_config` instead
   of hardcoding `"approle"`, and pass through the cert fields when present —
   `VaultConfig`/`build_auth_strategy` already accept them, no new auth code.
3. Add the conditional fields to `secret-manager-connection-dialog.tsx`
   (`authMethod === "cert"` conditional fields).
4. Update `secret-manager-help-dialog.tsx` and
   `doc/SECRET_MANAGER_INTEGRATION.md` to document the new method(s) —
   don't let those two drift from the code again.

---

## No concurrency cap on independent sibling branches

**Added:** 2026-09-21 · **Area:** `backend/services/execution/step_runner/runner.py`

### What we have

`StepRunner._run_wave` runs every node in one topological generation
concurrently via `asyncio.gather`, uncapped — no semaphore, no
`max_concurrency`-style knob. This is a deliberate asymmetry with device
fan-out, which has always had `fan_out.max_concurrency` precisely because an
uncapped burst there is a real, verified risk (a wide device count means a
simultaneous SSH-login/TACACS+ burst against real external infrastructure).
Branch-level concurrency was reasoned to be different in kind, not just
degree: the number of concurrent siblings in one wave is bounded by how many
independent branches a human actually drew on one canvas — low-cardinality
by construction, not attacker- or inventory-controlled the way a device
count is. See [[project_parallel_exec_discussion]] (memory) and
`doc/ARCHITECTURAL_OVERVIEW.md` → "Branch-level concurrency" for the full
design context this decision was made in.

### Original goal

Not a goal so much as a standing decision to revisit: keep sibling-branch
concurrency uncapped as long as the low-cardinality assumption holds in
practice.

### Why it's deferred

No concrete workflow has shown a canvas with wide-enough sibling fan-out
(tens of independent branches) to make this a real burst risk, unlike device
fan-out where the risk was obvious a priori (SSH/TACACS+ against real
network infrastructure). Adding a cap speculatively means a new
`branch_concurrency` (or similar) setting with no driving use case yet.

### When we revisit

If a real canvas is built with enough independent sibling branches feeding
into the same external resource (many parallel API/SSH calls with no shared
device-level pooling to fall back on) that an uncapped `asyncio.gather` burst
becomes a problem: add a `Semaphore` around `_run_wave`'s gather, sized by a
new run- or workflow-level setting, mirroring `fan_out.max_concurrency`'s
existing shape (`hatchet/workflows/workflow_run/fan_out_dispatch.py::_run_groups`)
rather than inventing a new pattern.

---

## No save-time warning for git-touching steps split across concurrent branches

**Added:** 2026-09-21 · **Area:** `backend/services/workflow/workflow_service.py`,
`backend/workflow_steps/registry.yaml`

### What we have

Two independent canvas branches (or a fan-out branch without an intervening
Fan In node) that both reach a git-touching step
(`store-artifact`/git-clone/git-pull/git-push/open-change-request)
configured against the *same* `git_repository_id` will each still run their
own clone/pull/commit/push — `services/git/repo_lock.py` (see
[[project_parallel_exec_discussion]]) makes this safe against working-tree
corruption, but it does not merge concurrent callers into one logical
operation, so the result is still N commits/branches/change-requests instead
of one. Today this is purely a documentation concern — `doc/WORKFLOW-STEPS.md`
→ "Writing concurrency-safe steps", the `registry.yaml` entries, and the
frontend `HelpWarning` panels all tell the workflow author to place such a
step after a join point, but nothing at save time actually checks for this
misconfiguration and warns or blocks it.

### Original goal

Detect, at workflow save time, a git-mutating step that is reachable via two
or more concurrent (non-joined) paths sharing the same `git_repository_id`
config value, and surface a validation warning (or block the save) —
mirroring the existing save-time structural check
`WorkflowService._validate_stop_here_not_in_fan_out` uses for a related
class of problem (a `stop-here` node placed somewhere fan-out semantics make
it meaningless).

### Why it's deferred

No concrete incident yet, and the existing policy already accepts the same
gap for the older, narrower case (a git step placed directly inside a
fan-out branch with no Fan In was never validated either — only
documented). Building real detection is also more involved than the
stop-here check it would mirror: that check is purely structural (is this
node inside a fan-out region), while this one needs to resolve each
candidate step's actual `git_repository_id` *config value* (not just its
position in the graph) and compare it across every concurrent path to the
same node — cross-node config comparison during save-time graph validation
has no existing precedent in this codebase.

### When we revisit

If this repeatedly produces duplicate commits/branches/change-requests for
real users (rather than being caught by the documented guidance): add a
`WorkflowService` save-time check, in the same architectural spot as
`_validate_stop_here_not_in_fan_out`, that walks the graph for each
git-touching step type, resolves its `git_repository_id` from config, and
flags any `GitRepository` id reachable via more than one concurrent
(non-joined) path — a warning first, since some workflows may intentionally
want N commits (e.g. distinct branches per caller), not an outright block.

---

## Expose Git Status results as device attributes (for route-on-attribute / templates)

**Added:** 2026-10-07 · **Area:** `backend/workflow_steps/git_status`,
`backend/workflow_steps/common/git_workflow_step.py`

### What we have

`git-status` routes on three outcomes (`clean` / `dirty` / `failure`) and stores its
full result (`reasons`, `modified_files`, `untracked_files`, `ahead_count`,
`behind_count`, …) in run-level `WorkflowContext.metadata["{node_id}.git_operation"]`.
That location is **not reachable** from `route-on-attribute`, Jinja `{bag.field}`
placeholders, `update-attribute` or `log-message`: attribute-path resolution
(`services/workflow_context/attribute_path.py`) only reads
`DeviceContext.attribute_bags`, never `WorkflowContext.metadata` (see
`doc/WORKFLOW-STEPS.md` → "Making values usable by steps"). So a workflow can
only branch on the coarse outcome (tunable via the `check_*` switches), not on one
specific reason or on a count such as `behind_count > 0`.

### Original goal

Let a workflow route or render on individual Git Status findings, e.g. "behind
origin but not ahead", or include `reasons` in a notification template.

### Why it's deferred

Undecided whether it is worth it. The idea: also write a compact summary into
every device's attribute bag (e.g. `git_status.clean`, `git_status.reasons`,
`git_status.ahead_count`, `git_status.behind_count`). Trade-offs to weigh:

- The result is per repository, not per device, so the same values get copied
  onto every device (same "one answer, N devices" shape as the Batfish
  Routing Table entry above).
- Needs a bag name that does not collide with existing/reserved bags (`parsed`,
  `run_input` are reserved), and file lists should stay out of the bag (size).
- `check_*` switches plus the three outcomes may already be enough.

### When we revisit

Only if a real workflow needs to branch or render on a specific reason/count.
Then: in `workflow_steps/git_status/executor.py`, write the summary via the shared
attribute-write helper (not a flat dotted key; use
`services.workflow_context.node_result` conventions for nesting), keep the
`git_operation` metadata as is, add a `produces`/Help-tab note, and cover it
with an executor test plus a `route-on-attribute` path-resolution test.


---

## Inventory ownership by user id (FK instead of username string)

**Added:** 2026-10-09 · **Area:** `backend/core/models/inventories.py`, `InventoryRepository`, `InventoryService`, `reference_resolver`

### What we have

Inventories are owned by the username *string* (`created_by`) in ~20 places.
`doc/plans/FABLE_MERGE_20261009.md` Phase 8 (S14 / R6) closes the hole without a schema
change: private inventories are carried along on user rename and removed on user delete,
and pre-existing orphans only produce a startup warning.

### End state

An `owner_user_id` FK to `users.id` (with back-fill migration), replacing all username-string
ownership checks, so identity can never be inherited via a reused username.

### What blocks it

Touches every ownership query/access check plus a data back-fill via the full migration
framework (`doc/MIGRATION_SYSTEM.md`); deliberately deferred as a larger, separate plan.


---

## Bring `pyright` to zero

**Added:** 2026-10-09 · **Area:** `backend/` (CI job `types` is advisory)

### What we have

Phase 9 of `doc/plans/FABLE_MERGE_20261009.md` converted `GitRepository` to `Mapped[...]` and
fixed the `BaseRepository` / `rowcount` findings: **73 → 54 errors** (pyright 1.1.406, basic mode).
Largest remaining: `services/cache/redis_cache_service.py` (8, `bytes | str` from redis),
`services/git/connection.py` (5), `routers/workflow_update_attribute.py` (4),
`services/workflow/workflow_git_service.py` (4), `services/execution/schedule_service.py` (4),
`services/nautobot/devices/update.py` (4) — mostly `str | None` narrowing.

### End state

`pyright` green, then drop `continue-on-error` from the `types` job in
`.github/workflows/backend-ci.yml`. Also bump the pin in `requirements-dev.txt` (the launcher
asks for 1.1.414+) and re-baseline.


---

## Finish the Phase 9 quality items that were only started

**Added:** 2026-10-09 · **Area:** `backend/models/`, `backend/workflow_steps/`, `backend/services/`

### Q7 — `extra="forbid"` on request models

`tests/unit/test_request_models_forbid_extra.py` now enforces the rule with a `LEGACY_LENIENT`
allow-list (82 request models left; credentials is converted). Convert one domain at a time:
add `ConfigDict(extra="forbid")`, delete the names from `LEGACY_LENIENT`, compare the keys the
frontend sends for that domain with the model, and exercise the flow in the browser. Order:
git repositories → workflows/runs → templates → sources → settings → the rest.

### Q1 / Q10 — long functions

The five worst functions were split into phase helpers (all behaviour covered by unit tests):
`configure_replace_config._process_one_device` 257 → 92, `undefined_and_unused.execute` 200 → 63,
`compare_pyats_snapshot._compare_one_device` 181 → 71, `git_workflow_step.run_git_workflow_step`
158 → 100, `open_change_request.execute` 154 → 118. The 50-line target was not reached for
`_process_one_device`, `run_git_workflow_step` and `open_change_request.execute` (long signatures,
docstrings and metadata dicts); split further when those files are next touched. Q10 (`DeviceCommonService`
pass-throughs, `InterfaceManagerService`, `DeviceUpdateService.update_device`, `GitService.push`) is untouched.


---

## Before flipping the repository to public (D7 leftovers)

**Added:** 2026-10-09 · **Area:** repo root, `SECURITY.md`, `backend/routers/git/debug.py`

- Run `gitleaks detect --no-git` and `gitleaks detect` (history) — the tool is not installed on the
  dev machine, so it was not run. (`git log --all -- '*.env' '*oidc_providers.yaml'` is already empty.)
- Add a real security contact to `SECURITY.md` if an e-mail address should be offered besides GitHub
  private vulnerability reporting (enable that feature in the repository settings).
- Decide whether `routers/git/debug.py` stays (dev-tools gated, 404 in production; keeping it is fine).
- Confirm the restored `.github/workflows/backend-ci.yml` actually runs green on GitHub (it has not been
  executed since it was restored).

---

## Hardening follow-ups noted in the Phase 1–9 reviews

**Added:** 2026-10-09

- **Chunked request bodies are unbounded in the app.** `limit_request_body` only checks a declared
  `Content-Length`; certificate uploads are bounded after Starlette spools them. Either enforce a limit
  in the reverse proxy (`docker/DOCKER.md`) or add an ASGI body-size limiter that counts streamed bytes.
- **Management AppRole material is still in the worker environment.** Phase 3 (V5) stops workers from
  *logging in* with the management role, but `production_guards` still requires its role/secret id.
  Move them to an API-only env file and relax the guard for worker processes.
- **`/health/ready` stays 200 when OpenBao is down** (V12 decision). Alert on `vault.ok == false`, or add
  an opt-in setting that makes vault readiness blocking.
- **A private inventory created between a rename/delete and the user change can still be orphaned**
  (`created_by` is not an FK). Closed by the "Inventory ownership by user id" entry above.
- **No 429-specific message in the frontend.** Per-user rate limits (Phase 6) return 429 with
  `Retry-After`; `useApi` shows its generic error text. Add a friendly "slow down, retry in N s" toast.
- **Per-process fallback for the rate limiters** when Redis is down is per-API-worker, so the effective
  budget multiplies by the worker count during an outage (accepted in the plan).
- **`nautobot/ops.py` error ladders** were left alone in Q2; if they are identical to the ISE ones, add a
  sibling `errors.py` decorator.
- **Request-model strictness for the Secret Manager and auth models** is done; see the Q7 entry above
  for the other 82.


---

## AI assistant: survive a full page reload

**Added:** 2026-10-10

- Sessions now survive navigation (in-memory store) and conversations can be saved on the server on
  request (`doc/ai_integration/AI_ASSISTANT.md` §18).
- **Still open:** an unsaved chat is lost on a full reload, by design (no browser storage for data that
  may contain device or run output). If that turns out to hurt, offer an opt-in autosave of the current
  chat as a draft conversation, or a "Save before reload" prompt, rather than writing to
  `sessionStorage`.

---

## AI assistant: Nautobot GraphQL queries

**Added:** 2026-10-10

- **Today** the inventory assistant (`doc/ai_integration/AI_ASSISTANT.md` §15) works from saved
  inventories (`resolve_inventory`), a name search and the attributes of one device. It cannot answer
  open questions such as "which devices are located in City A?" unless an inventory with that filter
  already exists.
- **To do:** let the assistant run read-only GraphQL queries against the Nautobot source, as the calling
  user, to answer such questions.
- **Design points to settle first:**
  - *Read-only:* accept queries only (no mutations; reject `mutation` / `subscription` operations by
    parsing the document, not by string matching) and keep it a pure read, like every other tool.
  - *Opt-in:* results are class B, so they must pass the same gates as the other inventory tools
    (§16): a result may contain only fields of categories the user enabled (basics, addresses, custom
    fields, config context). Filtering the selection set before sending is safer than filtering the
    response; unknown fields should be refused, not passed through.
  - *Bounds:* depth and complexity limit, a result row cap with a "N more" note, a timeout, and a
    per-user rate limit (`rate_limited(...)`), since each query hits Nautobot.
  - *Schema help:* a curated reference or a schema-introspection tool so the model writes valid queries
    instead of guessing field names (compare `get_template_reference`).
  - *Alternative to raw GraphQL:* a few structured tools (`find_devices(location=, role=, platform=)`)
    on top of the existing `NautobotSourceService`. They are easier to gate and validate, but less
    flexible. Decide whether raw GraphQL is worth the extra risk. Note that the project's rule
    "no client-side GraphQL" (`doc/claude/frontend.md`) concerns the browser; the backend already uses
    GraphQL internally.
  - *Proposal flow:* a query that is useful to keep (a filter) could later become an inventory-filter
    proposal the user reviews and saves.

---

## Isolate Jinja rendering outside the AI assistant

**Added:** 2026-10-10

- The AI assistant's trial render now runs in a child process (`backend/services/ai_assistant/render_isolated.py`)
  with a hard timeout, CPU/memory limits and capped `*` / `**` results (`_BoundedSandbox` in
  `template_render.py`).
- **Still exposed:** the template editor's own preview (`services/templates/templates_service.py`) and the
  Hatchet template steps render in-process with the stock `SandboxedEnvironment`. A template with nested
  loops or `'a' * 10**9` can burn a worker thread or memory there.
- **To do:** move the worker and the bounded sandbox to a shared helper (e.g. `core/`), use it from those
  paths, and decide the limits for long legitimate renders in workflow runs.

---

## AI assistant: secret tokens are only bound to a field *name*

**Added:** 2026-10-10 · **Area:** `backend/services/ai_assistant/redaction.py`,
`backend/services/ai_assistant/tools/workflow_tools.py`

- **What we have.** The assistant never sees a secret. It sees a `__SECRET_n__` token, and when the user
  asks for a workflow change the server puts the real value back (`Redactor.restore_data`). To stop the
  model from moving a secret somewhere the user never saw it, `tokenize_data` records the dict key each
  token came from and `restore_data` raises `SecretRelocationError` for any other key (the workflow
  tools return it to the model as a plan error). Added steps also show their secret-masked config in the
  proposal card.
- **The gap.** The binding is by key *name* only, not by position. A token that came from `password` of
  step A can still be restored into a `password` key of a different, new step B. That is the same kind
  of value in the same kind of field, so the damage is small. A step's `password` can only be reused
  where the plan already has such a field, and the proposal card shows the added step's masked config.
  A secret can no longer be moved into a message, command or other non-secret field.
- **To do (only if it matters).** Bind each token to its exact origin, for example
  `(node id, key path)` for a workflow step and `static_attributes[i].<key>` for run inputs, and restore
  it only there. Decide what happens when the model legitimately renames or splits a step: allow the
  token for the node it came from only, and keep it valid when the node id is unchanged. Add tests for
  moving a token between two steps that both have the same key.
- **Not worth doing** unless the assistant is given more write surfaces or the card stops showing the
  config of added steps.

