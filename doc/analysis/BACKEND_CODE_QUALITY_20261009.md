# Backend code quality — 2026-10-09

Reviewer: Grok 4.7
Reviewed on 2026-10-09 against `HEAD` at `2fd2fdc`.
Scope: production Python under `backend/`, tests excluded. Static reading and AST
scans only — no runtime profile, no test run. Line counts include comments and
blank lines.

Concentrated on:

1. Duplicate code.
2. Multiple paths that do the same work (git repository management in particular).
3. Long files, and whether the length is one function that should be split.
4. Python practice that gets in the way of tightening the above.

Finding prefixes: `G` (git paths), `D` (duplicates), `L` (length), `P` (Python
practice). Severity: **M** worth doing in the next cleanup pass, **L** backlog,
**info** observation or something already done well.

## 0. Verdict

The package split is healthy. 788 production files, 88 339 lines. 635 files are
under 200 lines. The longest file is 769 lines. Exact copy-paste of whole
functions is rare (three structural clone groups, all small helpers). Workflow
git steps, the artifact sink, and workflow JSON sync all go through
`GitService`. Five source types already share `routers/source_crud_factory.py`.

The cost is parallel implementations of the same operation, plus a few functions
that mix parsing, I/O, and result assembly:

* **Git has one engine and several side doors (G1–G4).** `GitService` is the
  documented place for URL checks and SSH/token auth. `pull`, `push`, and
  `fetch` still each repeat the token-URL swap, and `GitDebugService` pushes
  on its own. Readers and the UI sync both clone-or-pull, with different
  failure behavior. Commit history is walked three times.
* **Step executors copy the same device-failure helpers (D1).** `_build_outcomes`
  is the same function in eight executors. `_fail_device` is the same function
  in five.
* **Nautobot is two packages on purpose, with overlap at the edges (D2, D3).**
  `services/nautobot` mutates devices. `services/sources/nautobot` is the
  inventory source. Both metadata services hit the same custom-field endpoint,
  and interface writes exist in the older managers and in `interface_workflow`.
* **Length is in functions, not files (L1).** 36 functions are over 100 lines.
  Seven are over 150. The longest is `_process_one_device` at 257 lines.
* **416 broad `except Exception` handlers (P1),** and `GitService` raises from
  `clone` while `pull` and `push` return a result object (P2). That split is
  why the two sync wrappers exist.

### Findings at a glance

| Sev | Count | IDs |
|---|---|---|
| **M** | 6 | G1, G2, G3, D1, L1, P1 |
| **L** | 6 | G4, D2, D3, D4, L2, P2 |
| info | 2 | P3, P4 |

---

## 1. What was measured

| Check | Result |
|---|---|
| Production `.py` files under `backend/`, tests and `__pycache__` excluded | **788 files, 88 339 lines** |
| File-size buckets | under 200: 635 files / 35 102 lines; 200–399: 115 / 31 889; 400–599: 24 / 11 815; 600–769: 14 / 9 533 |
| Functions (AST) | **3 183**. 86 are ≥ 80 lines, **36 ≥ 100**, **7 ≥ 150** |
| Exact structural clones (AST dump, functions ≥ 12 lines) | **3 groups** |
| Normalized clones (names stripped, functions ≥ 15 lines, across files) | **9 groups** that span more than one file |
| `except Exception` and bare `except` | **416 handlers in 134 files** |

Largest packages by line count:

| Lines | Files | Package |
|---:|---:|---|
| 6 501 | 38 | `services/nautobot` |
| 5 331 | 25 | `services/git` |
| 4 910 | 43 | `workflow_steps/common` |
| 3 461 | 43 | `models` |
| 3 322 | 42 | `core` |
| 3 283 | 18 | `services/execution` |
| 2 669 | 20 | `routers/sources` |
| 2 523 | 9 | `services/sources` |

About 40 % of lines sit in files under 200 lines, and another 36 % in files of
200–399. The 38 files over 400 lines hold 21 348 lines, a quarter of the
backend.

---

## 2. Git: one engine, several side doors

`services/git/` is 5 331 lines across 25 modules. `GitService`
(`services/git/service.py`, 597 lines) is documented as the single place that
enforces `core.safe_urls.validate_git_remote_url` and applies SSH or token
auth. That claim holds for the workflow steps, the artifact sink, and workflow
JSON sync. It does not hold for debug push, commit history, or the connection
test.

| Entry | Lines | Relation to `GitService` | What it does |
|---|---:|---|---|
| `GitService` | 597 | Engine | clone, pull, push, commit, fetch, checkout, diff |
| git-clone / git-pull / git-push, `GitArtifactSink`, `WorkflowGitService` | — | Uses the engine | Workflow and artifact writes |
| `services/git/sync.py` `clone_or_pull` | 77 | Second policy | Readers. A failed pull keeps the cached tree |
| `GitOperationsService` | 421 | Second policy | UI sync and status. A failed pull is an error |
| `GitConnectionService` | 337 | Own clone | `subprocess git clone --depth 1` |
| `GitDebugService` | 695 | Own push | Commits and `origin.push` without `GitService` |
| `GitCacheService` | 266 | Own log | GitPython, then `subprocess git log` |
| `GitVersionControlService` | 148 | Own log | Branches, commits, file diff, its own cache |
| `GitFileService` | 694 | Own history | File content and a second file-history walk |

`GitRepositoryService` (238 lines) is database CRUD for `git_repositories`. It
is a separate job and should stay separate.

### G1 — Authenticated remote calls are copied four times (**M**)

`GitService.pull` (from line 263), `push` (367), and `fetch` (544) each:

1. call `validate_git_remote_url`,
2. open the repo if needed,
3. enter `GitAuthenticationService.setup_auth_environment`,
4. build env overrides,
5. temporarily `origin.set_url` for token auth,
6. run the remote command under `custom_environment`,
7. restore the original URL in `finally`, swallowing restore errors.

`GitDebugService._push_debug_commit` (`services/git/debug_service.py`, from
line 296) repeats steps 3–7 and then inspects `PushInfo` flags itself. It does
not call `GitService.push`, so a debug push does not pass through
`validate_git_remote_url` on that call (the repo was opened earlier by
`get_git_repo_by_id` → `open_or_clone`, which does check). Author config and
force-push behavior can also drift from the engine.

One helper should swap the token URL, apply the per-call env, run the remote
command, and restore the URL. Debug push should call `GitService.push`.

### G2 — Two sync policies for the same working tree (**M**)

`clone_or_pull` (`services/git/sync.py`) and
`GitOperationsService.sync_repository` (`services/git/operations.py`) both
clone when `.git` is missing and pull when it exists. Callers differ:

* Readers (`GitDeviceService`, `get_from_config`, `read_config`,
  `read_from_file`, `batfish_validate_facts`, `batfish_init_snapshot`,
  `routers/git/devices.py`) use `clone_or_pull`. A failed pull is logged and
  the cached copy is used.
* The git UI uses `sync_repository` / `sync_and_record`. A failed pull is
  stored as `error:<uuid>` and raised as `SyncExecutionError`.

`remove_and_clone` and `remove_and_sync` both only call `GitService.clone`.
`_clone_fresh` already deletes the target directory before cloning.

Collapse the two into one function with an explicit `on_pull_failure` policy
(`use_cache` vs `record_error`). Drop the remove-and-clone wrappers, or make
them call that function with `force=True`.

### G3 — Three readers of the same commit log (**M**)

* `GitCacheService.get_commits` walks `repo.iter_commits`, caches the result,
  and on any exception falls back to `subprocess git log`. Status payload
  filling in `operations.py` uses this.
* `GitVersionControlService.get_commits` walks `repo.iter_commits` again, with
  its own cache key (`repo:{id}:commits:{branch}`) and its own commit dict
  shape. The version-control router uses this.
* `GitFileService.get_file_history` walks the commit chain for one file and
  caches it. `GitCacheService.get_file_history` does the same job with another
  cache key.

One reader and one cache-key shape. The subprocess fallback belongs in that
reader, not as a second log format (`files_changed: 0` in the fallback, a
different author shape in the GitPython path).

### G4 — Connection test clones outside `GitService` (**L**)

`GitConnectionService.test_connection` is 135 lines and runs
`git clone --depth 1` via `subprocess` into a temp directory. It already uses
`validate_git_remote_url`, `GitAuthenticationService`, and
`build_git_env_overrides`. A throwaway shallow clone should stay off the
shared working tree. It should not grow a second clone command, a second auth
URL builder (`_build_clone_url` beside `GitAuthenticationService.build_auth_url`),
or a second error mapper.

---

## 3. Duplicate code

Normalized AST comparison (identifier names stripped) found these clones that
span more than one file. Smaller same-file duplicates are omitted.

| Size | Copies | What |
|---:|---:|---|
| ~19 lines | 8 | `_build_outcomes` in step executors |
| ~21 lines | 5 | `_fail_device` in step executors |
| ~47 lines | 2 | `_run_config_mode_on_device_logged` and `_deploy_on_device_logged` |
| ~17 lines | 4 | `_resolve_credentials` / `_resolve_test_credentials` on source routers |
| ~29 lines | 2 | `_build_filter_outcomes` and `_build_update_content_outcomes` |
| ~22 lines | 2 | `_build_upload_outcomes` and `_build_deploy_outcomes` |
| ~18 lines | 2 | `_do_request` in the pyATS and Mattermost clients |
| ~17 lines | 2 | BGP and OSPF Batfish outcome builders |

`execute` is the name of a ≥ 15-line function in **86** step modules (average
74 lines). That is the step protocol, not a clone. `get_config` (20 files) and
`_parse_config` (17 files) are the same kind of per-step boilerplate.

### D1 — Device failure and outcome helpers are copied (**M**)

`_build_outcomes` is structurally the same in:

* `workflow_steps/update_config_context/executor.py`
* `workflow_steps/read_from_file/executor.py`
* `workflow_steps/get_device_configs/executor.py`
* `workflow_steps/start_nautobot_job/executor.py`
* `workflow_steps/check_nautobot_job/executor.py`
* `workflow_steps/read_config/executor.py`
* `workflow_steps/update_nautobot_device/executor.py`
* `workflow_steps/get_nautobot_attributes/executor.py`

`_fail_device` builds the same `DeviceError`, copies the device with
`status=FAILED`, and returns `(device_id, failed, False)` in
`upload_config`, `get_device_configs`, `deploy_rendered_template`,
`add_to_nautobot`, and `get_nautobot_attributes`. The only real parameter is
the step id.

A helper in `workflow_steps/common` that takes the step id removes these
without merging the executors. The upload/deploy outcome pair and the
filter/update-content outcome pair are the same kind of extract, one size
smaller.

### D2 — Two Nautobot custom-field clients (**L**)

`services/nautobot/metadata_service.py` (`NautobotMetadataService`) and
`services/sources/nautobot/metadata_service.py`
(`NautobotSourceMetadataService`) both `GET extras/custom-fields/?content_types=dcim.device`
through `NautobotService.rest_request`. The source service adds a cache and
label shaping. Keep one fetch. Let the source service own the cache and the
label transform.

This is not a reason to merge the two Nautobot packages. `services/nautobot`
(client, resolvers, managers, creation, update) mutates devices.
`services/sources/nautobot` (`query_service.py` at 658 lines, persistence,
evaluator, live-query mixin) is the inventory source: Redis device index,
GraphQL filters, saved inventories. `DeviceQueryService` (one device) and
`NautobotSourceQueryService` (fleet filters) should stay separate.

### D3 — Two live interface stacks (**L**)

`services/nautobot/managers/interface_manager.py` (`InterfaceManager`) is still
constructed by `DeviceCommonService.interface_manager`.
`services/nautobot/devices/interface_workflow/service.py`
(`InterfaceManagerService`) is what `DeviceUpdateService` and
`DeviceCreationService` use. `DeviceManager` is in the same older package and
is still lazy-loaded from `DeviceCommonService`.

New interface work should go through `interface_workflow` only. The older
manager stays until `DeviceCommonService` stops constructing it.

### D4 — Nautobot source CRUD skipped the shared factory (**L**)

`build_source_crud_router` already builds list/get/create/update/delete for
pyATS, ISE, Catalyst Center, Mattermost, and Batfish. Nautobot inventories are
a different model (`routers/sources/nautobot/crud.py`, 369 lines, import and
export included), so a full merge is wrong. The exception ladder
(not-found, conflict, validation, internal) can still use the factory's
mapping instead of another copy.

The four `_resolve_credentials` / `_resolve_test_credentials` clones on the
pyATS, Catalyst Center, ISE, and Mattermost routers are the same extract, and
they sit next to the factory on purpose (the factory's own docstring leaves
test-connection in each module).

---

## 4. Long files and long functions

No production file is over 800 lines. File length alone is a weak signal. The
functions below are where a change has to be understood as one block.

### L1 — Seven functions are longer than 150 lines (**M**)

| Lines | Location |
|---:|---|
| 257 | `workflow_steps/configure_replace_config/executor.py` `_process_one_device` (315) |
| 200 | `workflow_steps/undefined_and_unused/executor.py` `execute` (126) |
| 181 | `workflow_steps/compare_pyats_snapshot/executor.py` `_compare_one_device` (279) |
| 158 | `workflow_steps/common/git_workflow_step.py` `run_git_workflow_step` (181) |
| 154 | `workflow_steps/open_change_request/executor.py` `execute` (291) |
| 153 | `workflow_steps/config_to_attributes/executor.py` `execute` (428) |
| 153 | `workflow_steps/batfish_validate_facts/executor.py` `execute` (275) |

`services/nautobot/devices/update.py` `update_device` is 149 lines, just under
the cut. `GitConnectionService.test_connection` is 135.
`GitService.push` is 108, and most of that is the URL-swap block from G1.

Split each into parse, act, and record. `workflow_steps/run_command/` already
does this (`exec_mode.py`, `config_mode.py`, `parsing.py`, `outcomes.py`) and
is the pattern to copy. `run_git_workflow_step` is shared, so splitting it
pays off for every git step.

### L2 — The longest files, and what actually makes them long (**L**)

| Lines | File | Split target |
|---:|---|---|
| 769 | `workflow_steps/add_to_ise/executor.py` | `_create_one_device` (107), `_resolve_device_fields` (104) |
| 751 | `services/nautobot/devices/update.py` | `update_device` (149): field prep, primary IP, interfaces |
| 743 | `services/execution/step_runner/runner.py` | `_execute_and_persist_node` (97) |
| 741 | `services/workflow/workflow_validation_service.py` | `_tier3_capability_flow` (132) |
| 694 | `services/git/debug_service.py` | Own read/write/push path (G1) |
| 693 | `services/git/file_service.py` | Listing, content, and history in one class (G3) |
| 683 | `workflow_steps/configure_replace_config/executor.py` | `_process_one_device` (L1) |
| 676 | `services/network/netmiko/connection.py` | 12 broad `except` handlers (P1) |
| 658 | `services/sources/nautobot/query_service.py` | Cache path vs live GraphQL fallback |
| 646 | `services/credentials/credentials_service.py` | Credential store. Not a second git-auth stack |

`DeviceCommonService` (`services/nautobot/devices/common.py`, 486 lines) is
long for a different reason: a large share of it is one-line delegation to
resolvers and managers. Folding those delegations away shortens the file
without a behavior change.

`workflow_steps/common/` at 4 910 lines is 43 files, not one dump. The largest
helpers (`content_resolver.py` 379, `git_workflow_step.py` 338,
`update_field_expression.py` 313) are shared on purpose.

---

## 5. Python practice

### P1 — 416 broad exception handlers (**M**)

`except Exception` and bare `except` appear 416 times in 134 production files.
The heaviest:

| Count | File |
|---:|---|
| 21 | `services/cache/redis_cache_service.py` |
| 17 | `services/git/debug_service.py` |
| 17 | `routers/sources/nautobot/ops.py` |
| 15 | `routers/sources/ise/ops.py` |
| 12 | `services/git/service.py` |
| 12 | `services/network/netmiko/connection.py` |
| 11 | `services/sources/nautobot/persistence_service.py` |
| 10 | `services/git/file_service.py` |
| 10 | `services/git/operations.py` |

In `GitService.pull` / `push` / `fetch`, the broad handler turns a programming
error into `success=False` and a string. Callers cannot tell a rejected URL
from a bug. Catch `GitCommandError`, `UnsafeURLError`, and the transport
errors each call site actually handles. The Redis cache and the source ops
routers are the same cleanup, and they are where the counts are highest.

### P2 — `GitService` mixes raise and result objects (**L**)

`clone` and `_clone_fresh` raise `GitCommandError` / `UnsafeURLError`.
`pull`, `push`, and `fetch` catch those and return `PullResult` / `PushResult`
/ `GitResult` with `success=False`. `commit` follows the result-object style.

`sync.py` and `GitOperationsService` each wrap that mix: one re-raises as
`ValueError` / `RuntimeError`, the other maps it onto `SyncResult`. Pick one
policy. Result objects are fine if every method uses them. G2 gets smaller
once this is consistent.

### P3 — Repository config is an untyped dict (**info**)

`GitService` methods take `repository: dict`. Branch defaults to `"main"` at
every call site (`clone`, `pull`, `push`, `fetch`, and the debug push). A
small typed config (`url`, `branch`, `auth_type`, `credential_name`,
`verify_ssl`, author name and email) would remove the `.get` chains. Not a
behavior bug. Do it when touching G1, not as its own project.

### P4 — Services raise HTTP errors (**info**)

`GitFileService` and `GitDebugService` call `raise_internal_server_error`.
That helper belongs at the router. Services should raise domain errors
(`NotFoundError` is already used in `GitOperationsService`). Workflow steps
that call these services otherwise have to catch an HTTP exception.

---

## 6. What is already in good shape

* Workflow git steps call `GitService` inside `run_git_workflow_step` and the
  per-repo advisory lock (`services/git/repo_lock.py`). `GitArtifactSink` and
  `WorkflowGitService` commit and push through the same engine.
* `GitRepositoryService` is database CRUD and does not clone. The module
  docstring says so, and the code matches.
* `build_source_crud_router` removed five copies of the source CRUD ladder.
* `run_command` is already split by mode, parsing, and outcomes.
* Exact structural duplication is small. The problem is parallel APIs
  (`get_commits` twice, file history twice, sync twice), not pasted modules.
* No production file exceeds 800 lines. 635 of 788 files are under 200.

---

## 7. Order of work

1. **G1 and P2 together.** One authenticated-remote helper inside `GitService`.
   Debug push calls `GitService.push`. `clone` uses the same result-or-raise
   policy as `pull` and `push`.
2. **G2.** One sync function. `on_pull_failure` is `use_cache` or
   `record_error`. Delete `remove_and_clone` / `remove_and_sync` as separate
   algorithms.
3. **D1.** `fail_device` and `build_outcomes` in `workflow_steps/common`,
   parameterized by step id.
4. **G3.** Version control and file history read through `GitCacheService`.
   One commit dict shape. Keep the subprocess fallback in that one reader.
5. **L1 and P1.** Split the seven functions over 150 lines. Narrow `except
   Exception` in `GitService`, `GitDebugService`, `redis_cache_service`, and
   the Nautobot and ISE ops routers.
6. **Leave the two Nautobot packages as two packages.** D2 and D3 are edge
   overlaps, not a merge.
