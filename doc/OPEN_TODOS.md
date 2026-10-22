# Open TODOs

Running list of known, deliberately-deferred cleanups. Each entry says what the
end state should be and what is currently blocking it, so a future session can
pick it up without re-deriving the context.

---

## Run Workflow step (`start-workflow`) and child runs

- **Live verification.** Built and covered by unit and render tests, not yet run end to end: a backup
  workflow (Get from User -> Get Nautobot Attributes -> backup steps) called from a change workflow, in
  both run modes, with a failing backup, a timeout, and cancelling the parent mid-wait. The two new
  `workflow_runs` columns (`parent_run_id` self FK, `ancestor_workflow_ids` JSON) have only been checked as
  generated SQL (`test_auto_schema_parent_run_fk.py`), not applied to a real PostgreSQL.
- **Pre-run validation of the target.** That the target reads `devices_input` in an enabled Get from User
  step, and that no required input is left empty, is only checked when the step runs. A Tier 1-3 finding in
  `WorkflowValidationService` would show it before a run starts (the builder panel already warns).
- **Waits are in-process.** The wait holds a worker slot and is lost on a worker restart; the started runs
  are not. A durable wait belongs to the orchestration layer (see the Wait & Run gate), not to a step.
- **AI assistant.** `propose_workflow` has no way to pick the target workflow of a Run Workflow step by name;
  the step is in the registry, but a plan would need a real workflow id from a tool result.

## Follow-ups noted while fixing the correctness findings

- **Batch event writer.** Live run events open one database session per event. A single writer task that
  batches inserts would cut connection use under a 300-device fan-out (the pool size is configurable now,
  `DATABASE_POOL_SIZE`; this is the structural fix).
- **One worktree per git operation.** All git-touching steps share one working tree per repository, serialised
  by the repository lease. A worktree per operation would let independent steps overlap; the lease, the
  branch scope and the commit pin are the interim safety.
- **Frontend verification runs (FV-1).** The parts of the frontend nobody has read (the canvas, nodes, edges,
  most step panels, settings, templates, inventory, reports, dashboard, tools) are covered by the conventions
  pass (Q4) and by Playwright flows: login → forced password change → build → run → view → schedule → logout,
  a revoked session followed by another user's login, two tabs saving one workflow, a 300-device fan-out run,
  a paused Wait & Run batch.
  *Done 2026-10-19 (`doc/HOWTO_TEST_THE_FRONTEND.md`):* sign-in, forced password change, builder (add, connect,
  auto layout, align, group), save / reopen / reload, export and import, the save-conflict dialog and the import
  dialog as a non-admin; in a second pass two real tabs saving one workflow (409, Keep editing, Overwrite, Reload),
  every page outside the builder loaded as admin and as a non-admin, and the schedule dialog; the product owner ran a
  workflow and created a schedule against the real engine. *Still open:* a revoked session, a 300-device fan-out
  run and a paused Wait & Run batch (they need a worker; the isolated test stack has a dead Hatchet endpoint), and
  Reports with data. See "Frontend test and verification backlog" below.
- **Retries for Nautobot, ISE and shim requests.** None of the clients retries an idempotent GET. A bounded retry
  with backoff belongs with the timeout review (O2).
- **Workflow restore can change visibility silently.** Decide whether restoring a version should keep the
  current visibility (recommended); a one-line change in `workflow_git_service.restore_version`.
- **Idle logout counts watching a run as inactivity.** A "run in progress" heartbeat on the shared activity
  clock would keep a person who is watching a long run signed in.
- **Webhook-driven approvals have no actor.** The run header could show "webhook" as the trigger source.
- **Agent-loop limits are not tied to the provider's real limits** (`MAX_OUTPUT_TOKENS`, stream options).
- **Running a workflow rewrites its definition** (`static_attributes` are persisted so the run dialog has a
  schema). Kept on purpose; it benefits from `expected_updated_at` only if the call sends it. "Run saved version"
  (unsaved canvas) does not: it reads the stored workflow and writes nothing (2026-10-19).
- **No undo/redo in the builder.** A product decision, not a defect.

## Route to Agent (`route-to-agent`, `/agent`)

Built 2026-10-22 (`doc/AGENT_INTEGRATION.md`); all of it is uncommitted work until merged.

- **Live verification.** Covered by unit suites, backend↔agent interop tests (real HTTP socket, Redis through
  `fakeredis`) and a built agent image answering the backend client; the HTTP transport was confirmed end to end by the
  product owner (2026-10-22). Not yet done: the Redis transport live, and a browser pass over
  Settings → Sources → Agents and the step panel, and a run against the real `manus-redis` with an
  `agents.acl` user (the generated ACL file in `docker/redis/start.sh` was tested in throwaway containers only,
  not by recreating the stack's `manus-redis`). Needs the isolated stack (`doc/HOWTO_TEST_THE_FRONTEND.md`).
- **Secret rotation without a gap.** Accept two secrets (current and previous) on both sides for a window;
  today the credential and `MANUS_AGENT_SECRET` must change together.
- **Pull transport.** The agent polls the app over HTTPS, so a remote agent needs no access to Redis. Needs a
  machine-facing API (token auth, queue state) on the backend; `AgentTransport` already leaves the room.
- **Redis over TLS for remote agents.** The repository does not configure it (no certificates to ship);
  today it is the operator's decision (VPN, `rediss://`, TLS proxy).
- **Persistent replay protection** on the agent, for example a small file or Redis `SET NX` for the Redis
  transport; rejected for now because "refuse anything older than the process" drops queued requests.
- **Batching** several devices per call, for fan-outs of hundreds of devices; templating inside `params`
  (deliberately not: another evaluation path).
- **Picking an agent needs `sources.agent:read`.** The step editor uses `GET /sources/agent`, so workflow
  editors without that permission get a 403. The editor now says so ("You don't have permission to list agents",
  naming `sources.agent:read`) instead of "No agents configured yet", and keeps the saved agent visible. This matches the other source types (a step editor needs that source
  type's read permission; `GET /sources/nautobot/configured-sources` is gated by `sources.nautobot:read` too,
  it only avoids `settings:read`). Optional: a minimal listing (id, transport) gated by `workflows:write` would
  also keep agent URLs and credential names from workflow editors.
- **Editor mirror of the secret-path rules.** `route-to-agent/config.ts` mirrors the destination, handler and
  output-key rules but not `secret_path_problem`; a secret path fails the step at start instead of in the editor.
- **DNS re-check on the call path** is deliberately skipped like for every source (`doc/SECURITY-NOTES.md`).

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

- Run `gitleaks detect` over the history. `gitleaks` is installed on the dev machine
  (`/opt/homebrew/bin/gitleaks`), and the `secret-scan` workflow already runs `gitleaks detect --no-git` on
  every push (green on `main` since 2026-10-19). Run any local scan on a **clean clone**: in the working tree it
  also reads gitignored files such as `backend/.env`. (`git log --all -- '*.env' '*oidc_providers.yaml'` is
  already empty.)
- Add a real security contact to `SECURITY.md` if an e-mail address should be offered besides GitHub
  private vulnerability reporting (enable that feature in the repository settings).
- Decide whether `routers/git/debug.py` stays (dev-tools gated, 404 in production; keeping it is fine).
- ~~Confirm the restored `.github/workflows/backend-ci.yml` actually runs green on GitHub.~~ Done: green on
  `main` on 2026-10-19 (commit 8505143), after the `integration-postgres` marker fix.

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
- ~~**No 429-specific message in the frontend.**~~ Done 2026-10-19: `useApi` builds "Please wait N seconds" from
  `Retry-After`. Not covered: the login route (`app/api/auth/login`) has its own error path and was not checked.
- **Per-process fallback for the rate limiters** when Redis is down is per-API-worker, so the effective
  budget multiplies by the worker count during an outage (accepted in the plan).
- **`nautobot/ops.py` error ladders** were left alone in Q2; if they are identical to the ISE ones, add a
  sibling `errors.py` decorator.
- **Request-model strictness for the Secret Manager and auth models** is done; see the Q7 entry above
  for the other 82.


---

## Report datasets identify devices by name

`report_data_records` rows are keyed by `(dataset, device name)`. `store-for-report` fails a second
device with the same name inside one step, but two devices with the same name at different locations
share one history across runs, because the report catalogue identifies devices by name. By design
for now; an author qualifies the dataset name (`interfaces_{location}`) to keep them apart. The same
rule holds for `store-in-db` / `get-from-db` (records are shared across workflows by name; a
`storage_key` placeholder separates same-named devices).

## AI assistant: keep the session while the user works — IMPLEMENTED

**Added:** 2026-10-10 · **Implemented:** 2026-10-10 (tested by the product owner)

- **Done:** the panel (open state, messages, draft) now survives navigation in an in-memory store keyed
  by surface and subject, and a conversation can be saved on the server with an explicit Save and
  resumed later (`ai_conversations`, list / resume / delete, 90-day retention). Design and limits:
  `doc/ai_integration/AI_ASSISTANT.md` §18; overview: `doc/ARCHITECTURAL_OVERVIEW.md` → "Sessions and
  saved conversations".
- **Remaining, deliberately not done:** an *unsaved* chat is lost on a full page reload (no browser
  storage for data that may contain device or run output). Only worth revisiting if it hurts: an opt-in
  autosave as a draft conversation, or a "Save before reload" prompt, rather than `sessionStorage`.
- **Not yet verified:** the retention purge on a real Hatchet worker.

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

## AI assistant: structured failure records — follow-ups

**Added:** 2026-10-11 · **Area:** `backend/models/failure.py`, `doc/ai_integration/AI_ASSISTANT.md` §19

The record (`FailureInfo`) is built for Netmiko, Catalyst Center, ISE, templates, git and Nautobot and
is covered by unit tests only. Open items:

- **Verify against real sources** (product owner, pending). Per source: a wrong credential, an
  unreachable host, and one source-specific failure, each with "Run and device content" off, asking the
  assistant what went wrong. Suggested cases: Netmiko (timeout, auth), Catalyst Center (self-signed
  certificate, wrong password), ISE (401 / 403), git (wrong token, non-fast-forward push), a template
  with an undefined variable, a Nautobot job that fails. Also check that:
  - the new `workflow_step_results.failure` column appears after the backend restarts,
  - a **fan-out** run carries the step-level record through `__step_errors__` to the aggregated step,
  - the classifier picks the right kind for the real error texts (git and Netmiko classify by
    inspecting text; add a case to the tests whenever a real failure comes out as `unknown`).
- **Show the record in the runs page.** The step result API already returns `failure` and `DeviceError`
  has it (`frontend/src/lib/workflow-context-types.ts`); the step result viewer
  (`step-result-viewer/device-error-list.tsx`) still shows only the message. Show kind, attempts and the
  hint next to it, and use it for filtering ("show all timeouts").
- **Live run events carry no record.** `workflow_run_events` keeps its `kind` (`connect_failed`,
  `auth_failed`, ...) and a text message. Decide whether events need a structured field or whether the
  step-level record is enough.
- **Not covered yet:** the pyATS steps (`get-pyats-*`, `compare-pyats-snapshot`, `add-pyats-testbed`),
  Batfish steps, `store-artifact`, `send-mail`, `notify*`, `secret-*` / Secret Manager and any other
  step that fails with a bare `RuntimeError(message)`. They still record text only; the fix is the same
  as for the others (classifier next to the client, `.failure` on its exception, or `from exc` in the
  cause chain).
- **Catalyst Center raise sites without a `code`** (for example the site-membership checks in
  `site_service.py`) classify as `unknown`. Set a `code` there.
- **Nautobot GraphQL `errors` bodies (narrowed).** Strict queries (`graphql_query(strict=True)`, used by
  the workflow-step lookups and the live/bulk query services) now raise `NautobotAPIError(code="graphql_error")`,
  classified `invalid_response`. The older resolvers in `resolvers/base_resolver.py` and
  `network_resolver.py` still log and return nothing; move them to strict queries when their callers
  can tell "not found" from "failed".
- **Run history per device** (`get_device_history`: the last N runs of this workflow for this device,
  status and failure kind only) was deferred in the design discussion. It would let the assistant say
  whether a failure is new or recurring.
- **Revisit the strict host / port rule** after testing. The record deliberately has no host or port
  (device addresses stay class B). If the assistant needs them to be useful, add them behind the
  inventory opt-in rather than to the always-visible record.

- **One-time purge of plaintext run inputs (S3-03).** Runs created before the `secret` run-input
  type may hold a former `string` input (for example a TACACS key) in `workflow_runs.run_inputs`.
  Operators should clear them once (`UPDATE workflow_runs SET run_inputs = NULL` or delete the old
  runs) and change the declaration of such inputs to type `secret`.

- **Isolate the remaining Jinja/regex steps (S4-07).** `/templates/render` and the regex probes now run
  in a killable child (`core/regex_isolated.py`, `services/ai_assistant/render_isolated.py`). The Hatchet
  steps `render-jinja-template` and `update-content` still evaluate author-written content in the
  worker process (authors are trusted); a batch API for the isolated runner is needed before moving them.

- **Container hardening trial (S6-09).** The compose files drop all capabilities but the few
  `start.sh`/supervisord need and set `no-new-privileges`, PID and memory limits, but `read_only: true`
  (with `tmpfs` for `/tmp`, `/run/supervisor`, `/var/log/supervisor`) is not enabled: it needs a trial of
  the real image (start, log in, run a workflow, upload a certificate, restart) to find every writable
  path. The runtime image still derives from the build stage; a slim runtime stage and
  `pip install --require-hashes` are open. The shipped proxy build ARGs remain in the `base` stage.
- **Image tags (S6-11).** `mattermost`, `litellm-proxy` and `batfish` require an explicit
  `*_IMAGE_TAG`; choose and review the tags, add digests for the images that hold secrets (OpenBao,
  LiteLLM, Postgres, Redis), and add the `docker` and `pip` (pyats-shim) ecosystems to Dependabot.
- **Deferred from the security review.** Single-use refresh tokens (`jti` denylist); `path_prefix` per
  Secret Manager connection; a batch API so `render-jinja-template` / `update-content` can use the
  isolated runner; `/health/ready` for monitoring now that port 8000 is unpublished; `docker/infisical/`,
  `Dockerfile.basic`, `Dockerfile.worker` and the helper scripts are dead code candidates (the worker
  image lacks `git`).

---

## Mirror run events into the Hatchet task log (`ctx.log`)

**Added:** 2026-10-18 · **Area:** `backend/services/execution/run_events_reporter.py`,
`backend/services/execution/step_runner/runner.py`, `step_runner/subgraph.py`, `backend/hatchet/workflows/`

### What we have

Run events (connect retries, per-device failures) go only to our own `workflow_run_events` table via
`emit_run_event()`, and the run page reads them from there. Nothing is written to the Hatchet task log, so
the log tab of a task in the Hatchet dashboard is empty for our runs. The operator view (run metadata, the
"Engine details" panel, the Workers card, "Open in Hatchet", see `doc/ARCHITECTURAL_OVERVIEW.md` → "Hatchet
run labelling and operator diagnostics") shows engine status, tasks, errors and fan-out children, but no log
lines.

### End state

Warning and error run events are also sent to the Hatchet task log with `ctx.log(...)`, so a person working in
the Hatchet dashboard sees a run's problems next to its metadata. Behind a switch that defaults to off.

### Why it is deferred

Small, but with trade-offs that need a decision (read from the SDK source, not measured):

- **Cost.** `ctx.log()` only queues the line (`queue.Queue(maxsize=log_queue_size)`, default 1000) and returns;
  a background thread sends it. Executors and device sessions never wait on the network. But the sender makes
  one gRPC `PutLog` call per line with retries and no batching, and a full queue drops the line (it logs a
  warning, never blocks). A 500-device backup with about 5 events per device is roughly 2,500 calls; a burst
  such as many devices failing to connect at once is when lines would be lost. `ctx.log` also writes each line
  to the worker's Python log, so the worker log would see every event twice.
- **Redaction.** The Hatchet log is a second store with a possibly wider audience. Messages must go through
  the same redaction as run events before they are sent, and some event messages can carry device output or
  exception text; check each kind.
- **Fan-out.** Each device group is its own Hatchet task, so hundreds of groups give hundreds of small log
  tabs. It helps only when you already know which group to open.
- **Little extra value.** The run page already shows per-device events from our table, and the operator view
  shows failed groups and error text.

### When we revisit

If operators ask for run problems in the Hatchet dashboard. Then:

1. Add an optional `hatchet_log` callable to `RunEventContext` (`run_events_reporter.py`); `emit_run_event`
   calls it after the database write inside its existing try/except, so it stays best-effort.
2. Bind `ctx.log` where the context is bound: `step_runner/runner.py` (~line 495) and `step_runner/subgraph.py`
   (~line 96). `StepRunner` does not see the Hatchet `Context` today, so thread it in from the task functions
   (`execute_steps`, `execute_device_group`).
3. Send only `warning` and `error` events (not connect and progress lines), redacted, one line each:
   `[warning] r1.lab: connect retry 2/3`. Add an environment variable (default off) to enable it.
4. Tests with a fake log callable: the happy path, and a failing or full `ctx.log` never breaking the run.
   Check a fan-out run with many failing devices against a real engine for dropped lines.

---

## Frontend test and verification backlog

**Added:** 2026-10-19 · **Area:** `frontend/`, `doc/HOWTO_TEST_THE_FRONTEND.md`

Left over from the vitest coverage passes and the Playwright passes (coverage 13.5 % → about 33 % statements,
about 40 bugs fixed; the ratchet in `frontend/vitest.config.ts` (36 / 28 / 27 / 36) keeps the gain).

### Decided: no import with references the user cannot list

A user without `credentials:read`, `git.repositories:read` or `sources.*:read` may **not** import a workflow that
references a credential, git repository or source: the import dialog needs a visible replacement for every
reference, and a user who cannot list them cannot choose one (decided by the product owner, 2026-10-19). Such a
user can still import a workflow that references none of them. The dialog says why ("the list could not be loaded,
probably because you don't have permission ... ask an administrator") and keeps Import disabled; the remap hook
test "still requires a replacement when the credential list could not be loaded" pins the behaviour. Do not
add a "keep the references unverified" path without a new decision.

### Smaller findings, not fixed

- **Pages request lists a workflow-only user may not read** (round 5, 2026-10-19: done except as noted). The
  requests that were pure noise are gated with `useHasPermission` (`hooks/use-has-permission.ts`): the `/workflows`
  git list (`useWorkflowGitRepositories`, `git.repositories:read`), the credential list in the template editor's options
  dialog and in the schedule parameter fields (`credentials:read`) and the Batfish source list (`sources.batfish:read`).
  The gated components (`workflow-manage-dialog`, `workflow-save-as-dialog`, `options-dialog`,
  `schedule-parameter-fields`, `batfish-options-tab`) have component tests since round 6 (2026-10-20).
  `/reports` and `/change-requests` were checked and need nothing (router-level `reports:read` /
  `change_requests:read`, which the viewer role has). **Fixed in round 6 (2026-10-20, decided by the product owner):**
  the Nautobot source lookup on `/inventory`, in the template editor, in the Nautobot step panels, in the step's
  source dialog and in the import remap no longer reads `settings`. They use
  `GET /sources/nautobot/configured-sources` (`sources.nautobot:read`, which the viewer role holds), which returns
  only `source_id`, `url` and `token_configured`. The settings form still reads and writes the rows, and a settings
  write refreshes the new query. `use-workflow-import-remap` is still not gated: a list that could not be loaded
  stays a reason to refuse the import.
- **The Overview minimap covers node handles** at about 1200×700 (fit view ignores the panel), and **new steps are
  placed only 44 px apart**, so they overlap until Auto layout runs. Both made handle clicks fail in the browser pass.
- **`/api/auth/me` is requested twice per page load.** Harmless, but one request would do.

### Found in round 6 (hook and component tests, 2026-10-20)

Fixed: `useDeviceFilter` kept an operator the next field does not offer (`within_include` on the name field) and the
previous field's values when "custom fields" or an emptied custom field was picked; `useSavedInventories` created a
duplicate when "update" came without an id and ignored a filter inventory with no conditions (the loader did nothing
and said nothing); `useWorkflowSave` depended on mutation objects and returned a new object every render; the Save As
dialog and the Manage dialog stored a cleared folder as `""` (an overwrite and an edit both wrote it; the workflow
service now stores the root for an update too, as `create` does); the Manage dialog hid the server's reason for a
failed edit and said nothing when a delete failed (for example a workflow with runs in progress); the options dialog
kept the test device of the previous Nautobot source.

Also fixed after a decision (2026-10-20): changing the Batfish source in the template editor now clears the network and
snapshot, and `sources.batfish:query` implies listing (the source list, networks and snapshots accept `:read` or
`:query`; create, update and delete still need `:write` / `:delete`; `build_source_crud_router(also_reads=...)`,
`require_any_permission` now names the accepted permissions in its 403).

Open:
- **Two toasts per failed inventory mutation.** `use-saved-inventory-mutations` / export / import toast in `onError`,
  and `device-selector.tsx` (`handleSaveInventory`, `handleSaveDeviceList`, `handleDirectSave`,
  `handleExportInventory`, `handleImportInventory`) toasts the same failure again in its `catch`. Remove the catch
  toasts (keep the `return false`); needs a `device-selector` component test first (no test exists).
- **Save As: "name unavailable" without `existing_id`** returns silently (`workflow-save-as-dialog.tsx`). The backend
  always sends the id, so this is unreachable today; show the message if the contract ever changes.
- **A credential reference field shows an empty select, not a hint,** when the user lacks `credentials:read`
  (`schedule-parameter-fields.tsx`).

Round 7 (2026-10-22): `device-selector` has a component test and no longer toasts twice (the mutation hooks toast in
`onError`; `useSavedInventories` now toasts the one failure no mutation covers, an update without an id).
`schedule-parameter-fields` shows a hint instead of an empty select without `credentials:read`; the Save As dialog
shows "name unavailable" without an `existing_id`. Thresholds 38/29/28/37.

Browser pass (isolated stack, 2026-10-22), what ran: viewer on `/inventory` (no 403, source `pw1` bound, no
`/settings` call); `:query`-only user in the template editor (`GET /sources/batfish` 200, both sources listed, a source
change cleared the network); workflow Manage dialog (rename and folder move onto an existing name: 409 shown inline;
cleared folder stored as `/`; failed delete toasts "Workflow not found"); workflow Save As (cleared folder normalised,
overwrite offer with the server message). Not run: the schedule credential hint and the Save As "unavailable without
`existing_id`" message in a browser (unreachable there), a Nautobot source that answers (the source was a dead address),
a Batfish source that answers, runs.

Found in that pass, not fixed:
- **Inventory rename onto an existing name succeeds.** `InventoryService.update_inventory` has no name check (create
  has one per creator), so Manage → Edit can produce two inventories with one name; the Save dialog's overwrite-by-name
  then picks one of them. Workflows got the 409 in round 6; inventories did not.
- **Manage Workflows keeps a deleted row after a failed delete** ("Workflow not found" toast, list unchanged, counts
  stale). A 404 on delete should refetch the list.
- **Legacy folder rows:** rows stored with `""` or `NULL` as the folder are read as `/` but not migrated. Decide on a
  one-time cleanup (and what to do with twins it would create). Asked, not acted on.

### Found in round 2 (hook tests)

Round 5 (2026-10-19): Save & Run writes the run-input schema once (the save carries it; `requestRun` takes
`schemaPersisted`), and a 429 now says how long to wait (`Retry-After`, `use-api.ts`) instead of the backend's generic
text. Round 4 fixed "Run saved version" using the unsaved canvas (it now reads the stored workflow and writes
nothing), `useDevicePreview` keeping stale selected ids after a new preview, and the `/workflows` 403 on the git list.

Fixed in round 2: ISE preview CIDR matching of junk, name-mode crash and missing `truncated`; unstable returns
in `useDevicePreview`, `useTemplateEditorDevice`, `useWorkflowRunActions`, `useCanvasNodeChanges`; Get Configs
posting an empty host. The ISE preview hook also refuses a blank group name or CIDR without a request now (the panel
already disabled its button). Still open:


### Second Playwright pass (2026-10-19, pages outside the builder)

Fixed in or after that pass:
- a read-only user saw New Template, Import, Edit and Delete on `/templates`;
- `/schedules` and `/change-requests` showed "No schedules yet." / "No change requests yet." after a 403;
- `/inventory` said "No Nautobot source is configured" after a 403 (now "Could not load the Nautobot source: ...");
- a schedule the engine SDK rejects showed raw pydantic text (now only the field and rule, detail logged);
- 37 router sites put `str(exc)` of a built-in exception (pydantic `ValidationError`, OS errors with paths) into a 4xx
  `detail` (now `client_error_message`, enforced by `scripts/check_http_4xx_leaks.py` in CI; the review of that
  change is in `doc/analysis/REVIEW.md`);
- non-admins got the built-in 20-minute idle timeout (and `switch_to_runs_on_start` defaulted) because both were read
  from `general/settings`, which needs `general_settings:read` (decided: every signed-in user may read them, now
  served by `GET /general/client-settings`, no export directory in it);
- mutation objects in dependency arrays (every hit is fixed; the last was `use-sources-settings-save.ts`, 2026-10-19).

Decided: **desktop only.** The tool has no small-screen layout (at 390 px the sidebar leaves about 100 px for the
page); `doc/claude/frontend.md` says so.

Not exercised in a browser: Reports with data, Inventory with a Nautobot source and the settings forms (sources,
users, git repositories) beyond loading them. The isolated stack has no Nautobot source.

### Not yet covered

- **Browser:** a revoked session, a 300-device fan-out run, a paused Wait & Run batch, Reports with data, the
  settings forms, and an inventory with a Nautobot source. Running a workflow and a schedule were checked by the
  product owner on the real stack; the isolated stack still has no working worker (decide how to give it one without
  letting it reach the real Hatchet engine).
- **Unit tests, largest gaps by uncovered statements** (after round 6, 2026-10-20; coverage 33.0 % → 36.7 %
  statements): `query-keys.ts` (a data file), `update-device-config` and `set-default-attributes-config` (58 each),
  then the remaining `.tsx` components (behaviour tests with the shared helpers in `src/test/`; layout is checked in
  the browser). Rank the list again with `coverage/coverage-summary.json`: it changed in round 6.
  Round 6 added the first component tests for the dialogs rounds 4 and 5 changed, and for the confirmation dialogs
  of `workflow-builder-page.tsx` (the rest of the page is stubbed, so the page's wiring beyond those is untested).
- **Raise the ratchet** (`coverage.thresholds`) after each round; never lower it. Now 36 / 28 / 27 / 36 against
  measured 36.7 / 28.4 / 27.8 / 36.4.
- **Pages that fetch more than they need** — the import dialogs were the case found; a quick check of the other
  always-mounted dialogs for queries that ignore `enabled` is cheap (`grep -rn "use.*Query()" frontend/src`).
