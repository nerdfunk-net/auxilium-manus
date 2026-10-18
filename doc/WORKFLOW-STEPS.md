# Workflow Steps

## Introduction

Workflow steps are the building blocks of the Auxilium Manus workflow engine. Each step
represents a single, well-defined operation that can be placed on the visual canvas and
connected to other steps via edges. Steps can model anything a network automation workflow
needs: selecting target devices from inventory, retrieving configuration, executing CLI
commands, evaluating conditions, or persisting output as a durable artifact.

The workflow engine treats every step as a node in a directed graph. The output of one
step becomes the available input of the next. Every step declares upfront what it
**requires as input**, what it **accepts as configuration**, and what it **produces as
output** — this contract is enforced at both load time and execution time.

Because the frontend canvas and the backend execution engine must both understand every
step in exactly the same way, each step is defined in two places that must always stay in
sync: a backend Python package and a frontend React component. The registry ties them
together by a shared step `id`.

---

## Directory Structure

```
backend/workflow_steps/           # Backend root — one sub-package per step
├── __init__.py
├── registry.yaml                 # Step registry (loaded at startup)
├── get_nautobot_devices/         # One directory per step (snake_case)
│   ├── __init__.py
│   ├── executor.py               # Step execution logic — REQUIRED
│   ├── config.py                 # Default configuration values (optional)
│   ├── models.py                 # Step-specific Pydantic models (optional)
│   └── nautobot/                 # Sub-packages allowed for complex steps

backend/services/execution/
├── step_registry.py              # Dispatch table — maps step id → executor.execute
└── step_runner.py                # Topological execution engine (do not modify per step)

frontend/src/
├── components/features/
│   └── workflow-steps/           # Frontend root — one sub-directory per step
│       └── get-nautobot-devices/ # Matches the step id (kebab-case)
│           ├── index.tsx         # Exports the PluginUIComponent (ConfigPanel)
│           ├── preview-dialog.tsx
│           ├── types/            # Step-specific TypeScript types (optional)
│           └── utils/            # Step-specific utilities (optional)
└── lib/
    └── plugin-ui-registry.ts     # Maps step id → PluginUIComponent via getPluginUI()
```

### Naming conventions

| Layer    | Convention   | Example                       |
|----------|--------------|--------------------------------|
| Backend  | `snake_case` | `get_nautobot_devices/`       |
| Frontend | `kebab-case` | `get-nautobot-devices/`       |
| Step id  | `kebab-case` | `"get-nautobot-devices"`      |

The `id` field in `registry.yaml` is the single source of truth that links the backend
directory, the frontend directory, and the UI registry entry.

---

## The Registry (`backend/workflow_steps/registry.yaml`)

Every step must have an entry in the registry. The backend reads this file once at
startup and exposes it via `GET /api/workflow-steps`. The frontend fetches it on boot
to populate the canvas palette.

### Entry structure

The file starts with a `schema_version` header and a `plugins:` list:

```yaml
schema_version: 1

plugins:
  - id: get-nautobot-devices      # kebab-case, unique, immutable
    name: Get from Nautobot       # Human-readable label shown in the UI
    description: >                # One-sentence description for the palette tooltip
      Select one or more target devices from the inventory.
    artifact_type: inventory_selector  # Semantic category (see below)
    directory: get_nautobot_devices    # Sub-directory inside backend/workflow_steps/
    enabled: true                 # false hides the step from the palette

    requires: []                  # Capabilities the step needs from upstream steps
    produces: [identity]          # Capabilities this step adds to WorkflowContext
    consumes: []                  # Capabilities removed after this step runs
    requires_parsed: []             # Parser keys required (when requires includes parsed)
    produces_parsed: []             # Parser keys produced (when produces includes parsed)
    outcomes:                     # Named exit handles for branching edges
      - name: success
      - name: failure

    metadata:
      configuration_input:        # Values the user sets in the config panel
        - name: nautobot_source_id
          description: ID of a Nautobot source configured under Settings → Sources.
          data_type: string
          required: true
```

> **Note:** Canvas connection validation uses `requires` / `produces` capability sets
> (subset check), not per-handle `data_type` matching. `metadata.configuration_input`
> drives step configuration forms only.

> **Failure-class outcomes carry the input state, not `produces`.** In
> `computeOutcomeProvides` (`frontend/.../workflows/utils/capability-graph.ts`) an
> outcome named `failure` / `fail` / `error` advertises the step's *input*
> capability set — the devices on that branch could not be processed, so the
> step's `produces` never materialised for them (matching the runtime, where a
> failed device is returned untouched). `mismatch` is **not** in this set: it is a
> normal result that still produces output. Name error outcomes `failure` (see the
> style guide) so this projection applies.

### Artifact types

| Value                   | Meaning                                      |
|-------------------------|----------------------------------------------|
| `inventory_selector`    | Selects or resolves target devices           |
| `configuration_management` | Reads device state or configuration        |
| `command_execution`     | Runs CLI commands on devices                 |
| `control_flow`          | Branches or gates the execution path         |
| `persistent_artifact`   | Stores durable output (backups, reports)     |
| `canvas_decoration`     | Visual-only canvas annotation (not executed) |

---

## Canvas decorations

Some **Visuals**-palette entries are **canvas decorations** — visual annotations that make
a workflow easier to read. They are **not** executable steps.

| Step id | Purpose |
|---------|---------|
| `label` | Configurable text (size, font, color) on the canvas |
| `background` | Colored rectangle always drawn **behind** other nodes |
| `step-group` | Container you open like a folder (see below) |

Contract:

- Registry: `artifact_type: canvas_decoration`, `palette_category: visuals`,
  **`executable: false`**, empty `requires` / `produces` / `outcomes`
- **No `executor.py`** and **no** entry in `step_registry.py`
- Frontend uses dedicated React Flow node types (`labelNode`, `backgroundNode`)
  with variable size — an intentional exception to the shared `WorkflowNode` /
  fixed `w-80`×`h-32` rule (see the style guide)
- No connection handles; edges to/from decorations are rejected
- `StepRunner` filters `executable: false` nodes (and edges that touch them) out
  of the execution plan — they never appear in run step results

`config.py` still provides defaults for the ConfigPanel. Decorations persist in
`canvas_nodes` with the rest of the layout.

### Containers — `step-group`

`step-group` is **not a canvas node**. Adding it from the Steps library (the "Add new Step" modal) creates an
empty `CanvasGroup` (`isContainer: true`) in `canvas_groups`; the registry entry only
makes it appear in the palette. Double-click the collapsed group to open it; steps added
inside become members. Purely organisational — execution stays flat and the backend
ignores `canvas_groups`. Like a step, a group dropped onto a background attaches to it
(`CanvasGroup.parentId`, position relative to the background) and moves with it.

- Boundary ports are derived from membership + edges (`utils/canvas-group-ports.ts`);
  moving steps in/out never rewires edges.
- Container groups survive at any size; groups made with "Group selected steps" dissolve
  below two members.
- Step Groups cannot be nested yet (dropping one while inside a group is rejected).
- Steps move in/out by drag-and-drop or the side panel, and connections to a
  collapsed group are resolved to a member step (picker when ambiguous). See
  [`doc/FEATURE-GROUPING.md`](./FEATURE-GROUPING.md).

### Pass-through decorations — `funnel`

`funnel` is a canvas decoration with one deliberate exception to the contract
above: **it does accept connection handles.** It exists to solve visual
clutter for many-to-one fan-in (e.g. several steps' `failure` handles all
wired into one `notify-on-error` node) the same way NiFi's funnel object
does — many edges converge on the funnel, and exactly one edge leaves it, so
the canvas only ever draws one line into the shared destination.

| Step id | Purpose |
|---------|---------|
| `funnel` | Accepts unlimited incoming edges; requires exactly one outgoing edge |

Contract:

- Registry: same as other decorations (`artifact_type: canvas_decoration`,
  `palette_category: visuals`, `executable: false`, empty `requires` /
  `produces` / `outcomes`) — no `executor.py`, no `step_registry.py` entry
- Frontend uses a dedicated small React Flow node type (`funnelNode`,
  `frontend/.../workflows/components/nodes/funnel-node.tsx`) rather than the
  fixed `WorkflowNode` card, same variable-size exception granted to
  `labelNode`/`backgroundNode`
- Like `WorkflowNode`, its input/output handle sides are configurable from the
  node config modal's General tab (`incomeHandleSide`/`outcomeHandleSide` on
  `data`, same `HandleSide` mechanism — see
  `HANDLE_SIDE_CONFIGURABLE_NODE_TYPES` in `node-config-modal.tsx`)
- Unlike `label`/`background`, a funnel's handles **do** accept edges: an
  unlimited number of incoming edges on its target handle, and exactly one
  outgoing edge from its source handle (enforced both at edit time —
  `isValidConnection` in `workflow-canvas.tsx` — and at save time —
  `validateCanvasWorkflow` in `workflow-validation.ts`). Chaining two funnels
  together is rejected at both edit time and by the backend splice below.
  Capability compatibility is **not** checked at edit time for edges
  touching a funnel — see `pre_step_guard`/`post_step_guard` below for where
  it's actually enforced.
- `StepRunner` does **not** simply filter a funnel's edges away like it does
  for `label`/`background`. Instead, `StepRunner._resolve_funnels` (called
  once, at the top of `StepRunner.load_execution_graph`, before
  `filter_executable_graph`/`topological_order` ever run) **splices** the
  funnel out: every incoming edge is rewired directly to the funnel's one
  downstream target, keeping the original edge's `sourceHandle` (outcome
  name) intact — so a `failure` edge funneled into `notify-on-error` still
  reads as a `failure` edge, and `pre_step_guard`/`post_step_guard` at the
  real destination enforce capability correctness exactly as if the sources
  had wired to it directly. Raises `ValueError` if a funnel has zero or more
  than one outgoing edge, or if a funnel feeds directly into another funnel.
- `load_execution_graph` is a **public** method precisely so external
  drivers that read a workflow's canvas and walk it themselves —
  `_run_steps_until_fan_out_or_done` in
  `hatchet/workflows/workflow_run/phase1.py`, which is the actual production
  entry point and does **not** go through `StepRunner.execute_all` — see the
  same spliced graph as `execute_all`/`resume_after_join`/`execute_subgraph`.
  Any future caller that reads `canvas_nodes`/`canvas_edges` off a
  `Workflow` directly and drives execution/reachability itself must call
  this instead of reading the columns raw.

---

## Backend contract

### executor.py — required for every executable step

Every step that runs during workflow execution must provide an `executor.py` module
inside its package. The module must expose a single async function with this exact
signature:

```python
# backend/workflow_steps/get_nautobot_devices/executor.py

async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    ...
```

| Parameter          | Type                  | Description                                        |
|--------------------|-----------------------|----------------------------------------------------|
| `config`           | `dict[str, Any]`      | `pluginConfig` from the canvas node                |
| `context`          | `WorkflowContext`     | Merged upstream step outcomes for this node        |
| `run`              | `WorkflowRun`         | ORM instance — use `object_session(run)` for DB   |
| `artifact_service` | `ArtifactService`     | Store/retrieve bulky content via `ArtifactRef`     |
| `node_id`          | `str`                 | React Flow node id (for metadata namespacing)      |
| `device_sessions`  | `DeviceSessionPool`   | Run-segment-scoped pool of live Netmiko sessions — see "Device sessions" below |

Non-SSH executors accept `device_sessions` but never use it — import
`DeviceSessionPool` under `TYPE_CHECKING` in those files so it costs nothing at
runtime (`from __future__ import annotations` makes the forward-ref annotation
safe). SSH executors pass it straight through to `NetmikoService(pool=device_sessions)`.

The function must return one or more `StepOutcome` values. Each outcome carries a
`WorkflowContext` snapshot for downstream routing via `sourceHandle` on canvas edges.
Outcomes are persisted to `workflow_step_results` and used by `StepRunner` when
assembling input context for dependent steps.

Raise a `ValueError` for configuration errors (bad input, missing field). Raise a
`RuntimeError` for unexpected execution failures. The `StepRunner` catches all
exceptions, marks the step failed, and skips remaining steps.

### Which exit to use — the outcome contract

| Situation | Exit | Device status | Step result |
|---|---|---|---|
| One device cannot be processed because of **its data or its remote state** (not found, rejected, ambiguous, value unusable, config line refused) | `failure` outcome, device `FAILED`, `DeviceError(code, message, failure=…)` | `FAILED` | `partial` / `failed` (derived from device counts) |
| The device needs nothing (already in the desired state) | a **declared** handle (`exists`, `unchanged`, `not_found`, …), only where the author legitimately wants another branch | `OK` | `success` |
| The step **cannot run at all** (bad configuration, missing credential, internal bug) | `raise` (`ValueError` config, `RuntimeError` execution) | — | `failed`, the walk hard-stops |
| A remote system is lost **mid-loop** | `success` = devices already processed, `failure` = the unprocessed ones carrying the transport `FailureInfo` (`workflow_steps/common/partial_outcomes.py::abort_outcomes`) | per device | `partial` |
| A step skips a device on purpose | stays on `success` only if documented for that step and counted in `metadata["<node>.skipped"]`; otherwise `failure` | `OK` / `FAILED` | `success` |

Rules: (1) a step never turns a healthy device into a `FAILED` one on its `success` outcome — the
engine (`post_step_guard`, `assert_no_newly_failed_on_success`) raises an internal error when one
does; devices that *arrive* failed are fine. (2) A step does not `raise` for a condition that
depends on one device's data. (3) Every handle in `registry.yaml` is emitted by some code path and
every emitted handle is declared. Inventory-style steps (Get from Nautobot, Get from List, …)
declare only `success`: their errors `raise`.

### Device CLI refusals, commit-model platforms, unknown platforms

`deploy-rendered-template` and `run-command` fail a device whose CLI refuses a command
(`fail_on_cli_error`, default on; closed marker list in
`services/network/netmiko/output_check.py`, only labels are ever reported, never device text).
The remaining commands are not sent and `write_config_after_execution` is skipped. A failed
config-mode operation always leaves config mode. On **IOS-XR and Junos the step commits** (a
failed commit rolls back and fails the device). Netmiko device types are resolved by exact alias
or Netmiko driver name only; an unknown platform fails that device with
`unsupported_platform` — set `network_driver_override` on the step. `get-device-configs` fails a
device whose `show` was refused or empty instead of storing the error text as a backup.

### The shared git working tree

`GitService` keeps one working tree per `GitRepository`. The repository lock has an owner token,
compare-and-delete release and a renewed lease (`GitRepoLease.ensure_held()` fails the holder when
the lease was lost). `open_or_clone()` checks out the configured branch (a dirty tree on the wrong
branch is refused, naming the Git Clone step) and moves an unusable tree aside as
`<dir>.corrupt-<time>` instead of deleting it; `git-clone` replaces the tree (restoring the old one
when the clone fails). `pull()` never merges into a different branch. Read steps use
`git_checkout()` / `agit_checkout()` (`services/git/sync.py`): the lease is held while the step
reads the files, so a change-request checkout cannot switch the tree underneath it; the pull is
deduplicated for a few seconds and a failed pull raises (`allow_stale_repository: true` accepts the
stale copy). Never keep the path after the `with` block.

Where the table is applied (CF-07): `upload-config`, `add-to-nautobot` (interface/IP/prefix/virtual
chassis problems fail the device and keep the created id), `batfish-init-snapshot` (a snapshot from
fewer devices than selected fails unless `allow_partial_snapshot`; skipped devices leave through the
new `failure` handle), `batfish-validate-facts` (empty expected facts fail the device),
`open-change-request` (identical configs leave through the new `unchanged` handle, no change request),
`route-on-attribute` (an unmatched device leaves through `failure`; route names `success`/`failure`
are reserved), `update-attribute` (a sealed source fails that device through the new `failure`
handle), `compare-data` / `route-on-content` (several exportable items fail the device with
`ambiguous_match`), `merge-content` (nothing to merge fails the device; repeated `json_merged` keys
become `<key>#2`), `config-to-attributes` (devices without parsed data fail), `get-ise-devices`
(names ISE does not know leave through `failure`).

### Behaviours that are on purpose

- **A git step that fails still emits an (empty) outcome.** `git-clone`, `git-pull`, `git-push`, `git-status` and
  the other git steps mark themselves failed through their `failure` handle with the structured cause; a
  device-agnostic successor wired to `success` still runs on an empty context. Wire the `failure` handle where
  that matters.
- **`get-nautobot-attributes` replaces the whole `nautobot` bag** of a device with what it fetched; a step that
  wrote `nautobot.*` keys earlier must run after it, not before.
- **Running a workflow persists its run-input schema** (`static_attributes`) as a side effect, because the run
  dialog needs a stored schema.

### Stored node configuration

Booleans in a node's `pluginConfig` are real booleans: the workflow service coerces the string spellings
(`"true"`/`"false"`, `"1"`/`"0"`, `"yes"`/`"no"`, `"on"`/`"off"`) of every field the registry declares as
`data_type: boolean` when a workflow is created or updated (an unrecognised string is a 400 naming the key) and
when it is read (older rows), so imports, AI patches and API clients are fixed once and every panel sees the same
value. `compare-data` and `compare-pyats-snapshot` record their diff at `parsed.<node id>.comparison_diff`; that is
an output, not a setting. The run page polls `GET /runs/{id}/progress` (statuses and timestamps, no step output) and
fetches the full run again only when it reports a change; `GET /workflows/{id}/runs` is paged (`limit`, `offset`).

### Route on Attribute expressions

A route value in braces is a predicate in a NiFi-style expression language:
`{key:function(args):function(args)}`. The key is an attribute path (empty key, `{:gt(10)}`, tests the
step's own `attribute_path`); functions chain left to right and the last must return a boolean. Anything
else in `values` is a literal compared with `attribute_path` (`case_sensitive` applies to literals only).
The former tokens `{exists}`, `{empty}`, `{null}`, `{absent}` are now `{:exists()}`, `{:isEmpty()}`,
`{:isNull()}`, `{:isAbsent()}` (state functions and `count()` must come first); the old spelling is rejected with a hint.
Functions: state `exists isEmpty isNull isAbsent` and `count()` (list length, dict keys, 1 for a non-empty scalar, 0 for empty/null/absent; a one-item list of a scalar is that scalar, so `[""]` counts 0 exactly as `isEmpty()` is true for it; e.g. `{parsed.x.serial:count():gt(2)}`); compare `equals equalsIgnoreCase startsWith endsWith
contains in`; numbers `gt ge lt le toNumber plus minus multiply mod`; text `toLower toUpper trim length
substring replace append prepend`; logic `not and({..}) or({..})`; regex `matches find`. A missing or
non-numeric value makes a comparison false, never an error; sealed secrets are never revealed. The engine is
`services/workflow_context/attribute_expression/` (`parser.py` whitelist parser, no `eval`; `evaluator.py`;
`functions.py`). Nesting of `and({..})`/`or({..})` is limited to 16 levels; `replace`/`append`/`prepend` results
over 1,000,000 characters (and `replace('', ..)`) are "no value". In a quoted string `\\` is one backslash and
`\'` a quote; any other backslash stays, so `'sw\d+'` is the regex `sw\d+`.

`matches`/`find` run in the isolated regex runner (`core/regex_isolated.py`, op `match_many`). Evaluation is
eager and the executor asks in rounds (`_answer_regex_questions`): each round evaluates every route for every
device, sends the questions it has no answer for to one child process, and repeats until nothing new is asked
(a text or pattern built from an earlier regex result needs one more round per level, at most 4, else the step
fails). The child answers each question on its own (0.25 s each, 1.5 s per batch): an invalid or empty pattern
or a stopped match fails only the devices that evaluate it (`failure` outcome, codes `invalid_regular_expression`
/ `regular_expression_stopped`, message without pattern or text). Patterns are never compiled in the API/worker
process, so a typo in a pattern shows at run time, per device, not at save. A malformed expression
(syntax, unknown function, empty pattern) fails the save (`invalid_route_expression`) and the run (`ValueError`). An empty, reserved (`success`/`failure`) or duplicate route outcome name fails the save too (`invalid_route_outcome`), with the same rules the executor applies.

### Step config flags

Every boolean and whole-number step setting is read with `workflow_steps/common/step_flags.py`:
`parse_bool_flag(config, key, default=...)` and `parse_int_flag(config, key, default=..., minimum=..., maximum=...)`.
`"false"`, `"0"`, `"no"`, `"off"` and `""` are false, `"true"`, `"1"`, `"yes"`, `"on"` are true, `None` means the default,
and any other string (`"ture"`) fails the step with a configuration error naming the key. Do not write
`bool(config.get(...))`, `config.get(...) is True` or a private `_parse_bool`: `scripts/check_flag_parsing.py` (CI) fails
on them. Per-device errors built from an exception go through
`workflow_steps/common/partial_outcomes.py::device_error_from_exception`: it keeps the message of a `ValueError` /
`FileNotFoundError` (written by the step) and reduces anything else (a database or HTTP client error) to the class
name plus a `FailureInfo`, so driver text, SQL and parameters never reach the persisted step result.
`update-content` has `fail_if_no_match` (default off): a device where every rule matched zero times fails with
`no_rule_matched` instead of passing its unchanged content on.

### Resolver contract: one meaning per path

`device.<scalar>`, bare scalars, `{placeholders}` and Jinja read the same value
(`services/workflow_context/device_scalars.py`):

| Path | Value |
|---|---|
| `device.primary_ip4` | the bare address (`10.0.0.1`) in every resolver; the stored form is `device.primary_ip4_cidr` (`10.0.0.1/24`) |
| `device.id`, `.name`, `.hostname`, `.platform`, `.network_driver`, `.source`, `.source_id` | the stored scalar |
| `<bag>.<key>` | a leaf of an attribute bag; a bag with exactly one key also answers to its bare name `<bag>` (kept for existing workflows; a second key makes it `None`) |
| `parsed.<key>...` | `DeviceContext.parsed`; in filename/path templates `parsed` is the small `output_key` bag |

`undefined-and-unused` writes `parsed.<output_key>.undefined.parsed` / `.unused.parsed`. The persisted copy of a
step result redacts every scalar below `nautobot.config_context` and `nautobot.local_config_context_data`
(`SECRET_BAG_SUBTREES`); the live context keeps the values. `log-attributes` masks well-known secret lines in
attached configuration text (best effort). `config-to-attributes` maps interface names to Nautobot types by prefix
(`GigabitEthernet`/`Gi` → `1000base-t`, `TenGigabitEthernet`/`Te` → `10gbase-x-sfpp`, …); an unknown name is `other`,
not `virtual`. `get-from-config` fails when the file cap (5000) cuts the scan short. At fan-in, per-child counters
(`*_count`, `*.total`, `*_counts`) are summed instead of keeping the first child's value.

### Bounded storage

The step output stored with a step result is capped (`STEP_OUTPUT_VALUE_MAX_BYTES`,
`STEP_OUTPUT_MAX_BYTES`, `services/execution/output_cap.py`): an oversized `parsed` / attribute-bag /
metadata value is stored as `{"__truncated__": true, "bytes": N}`; the live context passed to the next
step is untouched, and artifacts are unaffected. The artifact retention sweep keeps an artifact younger
than one hour even when its run is not in the sweep's snapshot, and meta files are written atomically.
`log-attributes` files are appended with `O_APPEND` and removed with their run (or by the sweep).
`GET /workflows/{id}/runs` answers at most 50 runs (`limit` up to 200, `offset`) and reports `total`.

### Notification caps and idempotence

`notify-on-error` posts at most `max_messages` (default 20) Mattermost messages per execution, then
one summary post; local notification rows are not capped. `notify` writes at most 100 rows plus a
final "... and N more devices" row. `notify-mattermost` cuts a post above 15 000 characters instead of
failing it. The run-level placeholders `{devices}` / `{device_count}` of the notification steps are
substituted last, so a device named `{device.hostname}` is printed, not evaluated. `collect-statistics`
replaces its `(run, node, device)` rows on a re-execution, so a Hatchet retry does not double them.

### Names as keys

Steps that store something under the device **name** (`store-in-db`, `store-for-report`, the secret
steps, `open-change-request` file paths) share one rule: two devices of one step that map to the same
key fail the later one (`duplicate_key`, failure kind `ambiguous_match`) instead of overwriting the
first (`workflow_steps/common/duplicate_keys.py`). `store-in-db` / `get-from-db` render `storage_key`
as a per-device template, so an author with same-named devices in two locations writes
`backup/{nautobot.location.name}`. `open-change-request` rejects two rendered files that land on one
repository path (a configuration error) and tells the author to add `{parsed.output_key}` or
`{command.index}` to the filename template. `batfish-init-snapshot` names its snapshot
`run-<run id>-<node id>` and its retention sweep never deletes the snapshot of a run that is still
active.

### Nautobot lookups: ambiguity and optimistic writes

Name, primary-IP and interface-IP lookups (`workflow_steps/common/nautobot_resolve.py`) are strict: a
GraphQL `errors` body raises `NautobotAPIError(code="graphql_error")` and several matches raise
`NautobotAmbiguousMatchError` (failure kind `ambiguous_match`) instead of picking the first one.
`update-config-context` re-reads and retries (at most 3 attempts) when the context changed between its
read and its write. REST path builders quote every interpolated value (`services/nautobot/common/rest.py`
`rest_query`), and list reads follow `next` through `rest_paginate` (bounded at 50 pages).

### Structured failure on `DeviceError`

When a step fails a device, pass a `FailureInfo` (`models/failure.py`) as
`DeviceError.failure` in addition to the free-text `message`. It records *why* in a closed
vocabulary (`phase`, `kind`, `attempts`, `elapsed_ms`, `hint`) with no free text, so the AI
assistant shows it without the user's content opt-in while the `message` stays class C
(`doc/ai_integration/AI_ASSISTANT.md` §19). Netmiko failures arrive already classified:
`NetmikoConnectionError.failure`, `CommandResult.failure`, `ConfigResult.failure` and
`DeployResult.failure` (`services/network/netmiko/failure.py`); copy them with
`failure_from_exception(exc)` or `result.failure`. Never add a free-text field to `FailureInfo`.
Done for `run-command`, `get-device-configs` and `store-for-report` (unusable values and duplicate device names are `config` / `bad_request`; database and unexpected errors are `internal` / `internal_error` with only the exception class, and their run message is a fixed sentence); other steps and sources still record only text.

### Logging — start and finish log lines are required

Every `execute()` must emit **at least two `logger.info()` calls**: one when the step
begins its work, one when it finishes. This makes a step's progress traceable in
`worker.log` even when devices, commands, or fan-out children are involved — the generic
`StepRunner` "Step started" / "Step finished" lines (see below) don't carry step-specific
detail.

```python
# backend/workflow_steps/my_new_step/executor.py
import logging

logger = logging.getLogger(__name__)


async def execute(
    *, config, context, run, artifact_service, node_id, device_sessions
) -> list[StepOutcome]:
    ...  # validate config, raise ValueError on bad input

    logger.info("my-new-step started run_id=%s node_id=%s", run.id, node_id)

    ...  # do the work

    logger.info(
        "my-new-step finished success=%d failure=%d run_id=%s",
        len(success_devices),
        len(failed_devices),
        run.id,
    )
    return outcomes
```

Rules:

- Prefix the message with the step's kebab-case `id` (matching `registry.yaml`), not the
  Python module name.
- Log the start line **after** config validation (so a `ValueError` for bad config doesn't
  emit a misleading "started" line) but **before** any I/O or per-device work begins.
- Log the finish line **after** all work completes, before building/returning
  `StepOutcome`s. Include whatever counts are cheaply available (success/failure counts,
  items processed) by reusing values you already computed — don't add bookkeeping solely
  for the log line.
- If several steps share one implementation helper (e.g. `git-clone` / `git-pull` /
  `git-push` / `git-status` all call `run_git_workflow_step` in
  `workflow_steps/common/git_workflow_step.py`), put the start/finish log lines once in the
  shared helper instead of duplicating them in every thin `execute()` wrapper.
- Some steps `del run` early because they don't need the ORM row beyond validation — use
  `context.run_id` instead of `run.id` in that case.
- Use `logger.info` for both lines. Reserve `logger.warning` / `logger.error` for actual
  problems; `StepRunner` already logs and persists exceptions, so don't duplicate a full
  traceback inside the executor.

**Where these logs go:** `backend/core/logging_config.py` configures the root logger for
both the API process and the Hatchet worker with two handlers — stdout (unchanged) and a
`RotatingFileHandler` writing to `LOG_DIRECTORY` (default `<data_directory>/logs`):
`app.log` for the API process, `worker.log` for the live/interactive Hatchet worker
(`hatchet/worker.py`), and `worker-background.log` for the background-tier worker
(`hatchet/dynamic_worker.py`) — workflow steps execute in whichever worker owns the run.
Each process writes its own file so two `RotatingFileHandler`s never share one path.
Rotation size/retention are controlled by `LOG_MAX_BYTES` /
`LOG_BACKUP_COUNT` (see `backend/.env.example`). Because `logger =
logging.getLogger(__name__)` loggers propagate to root by default, no per-step setup is
needed beyond the two calls above.

`StepRunner` (`services/execution/step_runner.py`) already logs a generic `"Step started
node_id=... type=... run_id=..."` / `"Step finished node_id=... type=... status=...
summary=..."` pair for every step — the latter includes any `StepOutcome.summary` an
executor sets. The per-executor start/finish logs above are additional, step-specific
detail; they are not a replacement for setting `StepOutcome.summary`, and vice versa.

### Registering a new step

After creating `executor.py`, add one import and one dict entry to the dispatch table:

```python
# backend/services/execution/step_registry.py

from workflow_steps.get_nautobot_devices.executor import execute as get_nautobot_devices
from workflow_steps.my_new_step.executor import execute as my_new_step  # ← add

STEP_REGISTRY: dict[str, StepExecutor] = {
    "get-nautobot-devices": get_nautobot_devices,
    "my-new-step": my_new_step,  # ← add
}
```

The `step_registry.py` file must remain a thin dispatch table — no business logic.

### Execution path

```
Hatchet workflow task
  └── StepRunner.execute_all()          services/execution/step_runner.py
        └── STEP_REGISTRY[step_type]    services/execution/step_registry.py
              └── execute()             workflow_steps/{step}/executor.py
```

External code (routers, other services) must never import `workflow_steps` **step
packages or executors** directly. The `StepRunner` is the only authorised caller of
executors.

**Exemption:** shared helpers under `workflow_steps/common/` may be imported by
routers and services when they expose pure utilities (path sanitization, attribute
path probes, regex transforms, etc.). Do not import executor modules or step
packages from outside `StepRunner` / `STEP_REGISTRY`.

### Device sessions

**Full design:** `doc/DURABLE_SSH_SESSION.md`.

SSH steps (`run-command`, `get-device-configs`, `deploy-rendered-template`,
`merge-config`) share
live Netmiko sessions across steps within one execution segment (a phase-1 walk,
a phase-4 post-join resume, or a fan-out child) via `DeviceSessionPool`
(`services/network/netmiko/session_pool.py`). `StepRunner` owns one pool per
segment and injects it into every executor call as `device_sessions`.

Key points for step authors:

- Pooling is transparent — a step that targets the same device + credential as
  an earlier step in the same segment silently reuses the socket. No canvas/UI
  change is required.
- **Invariant:** an executor must leave a pooled session in privileged-exec base
  state before returning (config mode always exited, no pending interactive
  prompts). A later step may reuse the same live session, so leaving it mid-prompt
  or in config mode corrupts the next step's command.
- **Fan-out boundary:** sessions never cross a Hatchet parent→child task
  boundary. Each fan-out child gets its own pool; a workflow that SSHes to
  devices both before and inside a fanned-out branch pays one extra login per
  device at the boundary — rare by construction, accepted.
- **Suspend:** `DeviceSessionPool.suspend()` disconnects every live session
  but keeps the pool usable (the next network step reconnects lazily) —
  `close()` calls it internally. Nothing in `StepRunner` calls it directly
  today; its only call site was the per-node debug-mode pause, which has
  been removed (see [Fan-out execution](#fan-out-execution) for the
  `stop-here` step that replaced it for mid-run inspection).
- Never store `device_sessions` or a session object beyond the `execute()` call
  — the pool is scoped to the segment and closed by its owner in a `finally`
  once the segment ends.
- `login-successful` is the one exception to transparent reuse: it always
  opens a disposable side connection (`DeviceSessionPool.probe_login`) to
  force a real new authentication, and never reads, locks, or mutates a
  pooled session — see `doc/refactoring/FORCE_SSH_LOGIN.md`. Pooled sessions
  for the same device stay open throughout, so a failed probe still leaves a
  live session available for a rollback step.
- Emergency rollback: `settings.netmiko_session_pooling = False` restores the
  legacy fresh-session-per-call behavior without a code change.
- `run-command`'s `execution_mode: "config_mode"` branch calls the exact same
  `NetmikoService.deploy_config()` codepath as `deploy-rendered-template`, so it
  inherits the same base-state-on-return guarantee (`exit_config_mode()` always
  runs, including after a mid-loop `auto_confirm_prompts` confirmation) without
  any new code.

### Calling pyATS from a step

A step must **never** `import pyats` / `import genie` directly. pyATS/Genie
is not installed in the backend's own Python environment at all (its
published wheels don't confirm support for the backend's Python version, and
its dependency tree risks colliding with the app's own deps) — it runs in a
separate Docker container (`/pyats-shim`) behind a thin FastAPI wrapper. A
pyATS-backed step calls that wrapper over HTTP through the same app-scoped
service-client pattern already used for Nautobot and Cisco ISE:

```python
shim = service_factory.get_pyats_app_service()          # PyATSShimService
credentials = pyats_source_config_service.resolve_credentials(source_id)  # PyATSCredentials
response = await shim.run_job(
    credentials, operation="parse", devices=[...], commands=[...],
)
```

Full shim HTTP contract, job/easypy execution model, and container
architecture: **doc/PYATS_INTEGRATION.md**.

Reference implementations: `workflow_steps/add_pyats_testbed/executor.py`
(resolves a credential + pyATS source once for the current device list and
writes a reusable connection bundle into each device's
`attribute_bags["pyats_testbed"]`, producing the `pyats_testbed` capability)
and `workflow_steps/get_pyats_running_config/executor.py` (a downstream step that
`requires: [identity, pyats_testbed]` and calls the shim using that bundle —
no credential/source configuration of its own). Any new pyATS-backed step
that needs the same device connection info should declare
`requires: [pyats_testbed]` and read the bag rather than re-resolving its own
credential, the same way Add Testbed → Get & Parse Config do.

### Normalized command-output parsing (`run-command`)

`run-command`'s `parser` config selects **at most one** parser — `"none"` (default,
raw text only), `"textfsm"` (netmiko/ntc-templates, no extra setup), or `"genie"`
(via the pyATS shim above, requires `pyats_source_id`). Whichever is selected, the
parsed result lands in the **same shape**, inline in `DeviceContext.parsed`, at:

```
parsed.<parsed_output_key>.<command> = {"parsed": <data-or-None>, "error": <str-or-None>}
```

`parser` is mutually exclusive with `execution_mode: "config_mode"` and with
`auto_confirm_prompts: true` — `run-command` raises a `ValueError` at execute-time if
`parser` is anything other than `"none"` while either of those is set. Config-mode
output isn't line-addressable the way exec-mode output is (see
`deploy-rendered-template`'s identical constraint), and a confirm-handling command's
output isn't guaranteed to be well-formed TextFSM/Genie input either. `parser`
defaults to `"none"`, and `execution_mode` defaults to `"exec_mode"` — set `parser` to
a real value only when staying in `exec_mode` with `auto_confirm_prompts` off.

`auto_confirm_prompts` answers two kinds of interactive prompt with Enter: Cisco
`[confirm]` prompts (`reload`, `no username …`) and the `Destination filename […]?`
prompt of `copy running-config startup-config`. Both are recognised by
`NetmikoDeviceSession._send_command_confirming`, and a `Destination filename` text
earlier in the output is not treated as a pending prompt. A second prompt after that
answer is not handled — it times out at `read_timeout`.

`parsed_output_key` defaults to `"parsed"`. This is the one deliberate parity point
between the two parsers: a downstream step (`route-on-attribute`'s `attribute_path`,
a Jinja template, `log-attributes`) reads `parsed.<parsed_output_key>.<command>.parsed`
the same way regardless of which parser produced it — it never branches on
`parser == "textfsm"` vs `"genie"`.

Both parsers are **non-fatal per command**: a command with no matching TextFSM
template, or no Genie parser, gets `{"parsed": None, "error": "<reason>"}` for that
command only — it never fails a device whose raw command execution already
succeeded. Because of this, `Capability.PARSED` is never a guaranteed `produces` for
`run-command` (see `effective_produces` in `services/workflow_context/guards.py`); a
step that needs structured command output should declare `requires_parsed:
[<parsed_output_key>]` rather than assuming the capability.

**Do not build a second bridge from raw/parsed command output into `device.parsed`.**
**Untrusted data in templates.** Data from Nautobot, CSV, git and run inputs is untrusted input to
device command lines. `render-jinja-template` rejects, per device, any `{{ value }}` that contains a
line separator — LF, CR, VT, FF, FS, GS, RS, NEL, U+2028, U+2029, everything `str.splitlines()` splits on
(`FailureKind` `unsafe_template_value`) — unless the step sets `allow_multiline_values`
(switch "Allow values with line breaks"). Line breaks in the template text itself are the author's own
and are fine; `{{ list | join('\n') }}` is a value and needs the opt-out. `deploy-rendered-template`
splits the rendered text on `\n` only, so the renderer and the splitter agree on what ends a command.

`filter-output` and `render-jinja-template` also write to `device.parsed`, but only
artifact-ref *metadata* (`{"artifact_ref": ..., "size_bytes": ...}`) for their own
large/exportable content — that is a different, intentionally separate contract for
`store-artifact`-style consumers, not something `route-on-attribute` or a Jinja
`parsed.*` placeholder can read as a literal value. `run-command`'s `parser` output
above is the only inline, attribute-path-readable structured data a command
produces.

### Applying a partial config — `merge-config`

`merge-config` (`artifact_type: command_execution`) is a small SSH step that layers a
**partial** config file already on the device onto the running config by issuing
`copy <source_filename> running-config` and answering the one interactive prompt,
`Destination filename [running-config]? `, with Enter. IOS runs the file in
non-interactive batch mode, so per-line `[confirm]` prompts (e.g. a changed `username`)
are auto-bypassed by the copy engine; the prompt handler
(`NetmikoDeviceSession.merge_running_config`) still runs a small bounded loop
(`_MERGE_MAX_PROMPT_ANSWERS`, default 5) so an unexpected extra prompt is answered rather
than hanging, and a device is failed if the transcript carries `%Error` / `Invalid input`
/ `%Warning`. It reuses the Run Command backend (`NetmikoService` / `DeviceSessionPool`,
`resolve_config_reference` + `resolve_ssh_credential`, `resolve_connection_device_type`)
and exposes only `source_filename`, credentials, `network_driver_override`, and
`read_timeout`. It adds no capability (`produces: []`), so it is **not** in the
`run-command` `effective_produces` special-case in `services/workflow_context/guards.py`.

`merge-config` and `configure-replace-config` are the two config-deploy steps; choose by
what the staged file contains:

- **`merge-config`** — a **partial** file (a rendered template covering only a few
  sections, an ACL snippet, some `interface` blocks). Adds those lines, leaves everything
  else untouched, no rollback timer.
- **`configure-replace-config`** — a **complete** device configuration (a full, edited
  `show running-config`). `configure replace … force time N` + `configure confirm` (via
  the pyATS shim) makes the running config match the file exactly — it *removes* lines the
  file omits — with a device-native rollback timer and pre/post diff verification. **A
  partial file fails this step**: it either strips out everything the file doesn't mention
  or fails `configure replace`'s own validation.

### Optional modules

| File         | Purpose                                              |
|--------------|------------------------------------------------------|
| `config.py`  | `get_config() -> dict` — default values for the step |
| `models.py`  | Step-specific Pydantic models                        |

A `config.py` is exposed via `GET /api/workflow-steps/{plugin_id}/get-config` and used
by the frontend to pre-populate a step's config panel.

```python
# backend/workflow_steps/get_nautobot_devices/config.py
def get_config() -> dict:
    return {
        "nautobot_source_id": "",
        "inventory_id": None,  # selected saved inventory, resolved live on every run
        "device_filter": {"logic": "AND", "negate": False, "id": "root", "items": []},  # ad-hoc
    }
```

Sub-packages are allowed for complex steps that need to split logic across multiple
modules (e.g. `get_nautobot_devices/nautobot/`).

---

## Frontend contract

Every step that has user-configurable properties must export a `PluginUIComponent` from
its `index.tsx`:

```typescript
import type { PluginUIComponent } from "@/components/features/workflows/types/plugin-ui";

export const MyStepPlugin: PluginUIComponent = {
  ConfigPanel: MyStepConfigPanel,
  // Optional: detailed how-to for the built-in Help tab (beside Description)
  HelpPanel: MyStepHelpPanel,
};
```

The step configuration modal always shows **General**, **Description**, and **Help**.
**Configuration** appears when the step has a `ConfigPanel` (or registry
`configuration_input`). Extra tabs can be added via `modalTabs` (e.g. Probe).

`HelpPanel` is step-authored usage documentation (examples for every control).
When omitted, Help still appears with a short placeholder. Reuse helpers from
`workflow-steps/shared/step-help.tsx` (`HelpSection`, `HelpCode`, `HelpExample`,
`HelpWarning`). Reference: `get-nautobot-devices/help-panel.tsx`.

The `ConfigPanel` component receives:

| Prop       | Type                                    | Description                              |
|------------|-----------------------------------------|------------------------------------------|
| `nodeId`   | `string`                                | Stable React Flow node id                |
| `config`   | `Record<string, unknown>`               | Current step configuration               |
| `onChange` | `(config: Record<string, unknown>) => void` | Must be called on every user change  |
| `onPreview`| `() => void`                            | Trigger a preview action                 |

The component must be registered in `frontend/src/lib/plugin-ui-registry.ts`:

```typescript
import type { PluginUIComponent } from "@/components/features/workflows/types/plugin-ui";
import { GetNautobotDevicesPlugin } from "@/components/features/workflow-steps/get-nautobot-devices";

const PLUGIN_UI_REGISTRY: Record<string, PluginUIComponent> = {
  "get-nautobot-devices": GetNautobotDevicesPlugin,
  // add new steps here
};

export function getPluginUI(pluginId: string): PluginUIComponent | undefined {
  return PLUGIN_UI_REGISTRY[pluginId];
}
```

### Canvas node appearance

Steps do **not** ship their own React Flow node component. Every step is rendered by the
shared `WorkflowNode` in
`frontend/src/components/features/workflows/components/nodes/workflow-node.tsx`.

Canvas appearance is driven by the registry entry:

| Registry field    | Canvas use                                      |
|-------------------|-------------------------------------------------|
| `name`            | Node title — must be fully visible (no truncate)|
| `description`     | Subtitle under the title (`line-clamp-2`)       |
| `artifact_type`   | Icon tile colour and default Lucide icon        |
| `outcomes`        | Source handles; label + handle colours          |
| `requires`        | Whether a target (input) handle is shown on the left |

**Sizing:** all nodes are `w-80` × `h-32`. Never add per-step width/height overrides.

**Input handle:** when `requires` is non-empty, a single light-gray target handle appears
on the left (`!bg-slate-300 !border-slate-400`).

**Output colours:** the shared renderer applies green to `success` / `match` / `pass` and
red to `failure` / `fail` / `error` / `mismatch` on source handles. Name outcomes accordingly in
`registry.yaml` so branching edges are visually consistent.

**Optional icon override:** if the default `artifact_type` icon is not distinctive, add one
entry to `nodeIconsByKind` in `workflow-node.tsx` — do not fork the node layout.

Full rules (title wrapping, outcome palette, fan-out badge, anti-patterns): see
`doc/WORKFLOW-STEPS-STYLE_GUIDE.md` → **Canvas node (React Flow)**.

---

## Static attributes (run-scoped trigger inputs)

Some workflows need a value supplied fresh each time an operator triggers a run
manually — a TACACS+ key for a rollout, a VLAN ID, a one-off note — rather than a
value baked into the canvas at design time. This is **not** a canvas step:

- **Declaration**: a workflow-level schema (`Workflow.static_attributes`, a list
  of `{name, type, ref_kind?, default, required}` — `type` is `string` | `number`
  | `boolean` | `reference` | `secret`) edited in the properties panel's "nothing selected"
  state (`WorkflowStaticAttributesPanel`), and saved as part of the normal
  workflow Save action — the same way `canvas_nodes` / `canvas_edges` are.
- **`secret`-typed attributes** (S3-03) are typed into a masked field and **sealed on
  receipt** (`services/execution/run_input_validation.py` → `seal_secret`) before anything
  is persisted. `workflow_runs.run_inputs`, `workflow_schedules.run_inputs`,
  `change_requests.run_inputs`, the `run_input` attribute bag and the Hatchet payload only
  ever hold the Fernet envelope; every API response shows `***REDACTED***`. A secret cannot
  have a default (it would sit in the workflow definition in plaintext) and cannot feed a
  `run_param` config reference. `secret-set` reads it with `reveal_secrets=True`. Editing a
  schedule leaves a stored secret alone unless a new value is typed.
- **`reference`-typed attributes** don't carry a literal — they carry a pointer
  to another row, resolved at dispatch *scoped to the triggering user*. `ref_kind`
  is required and selects the resolver
  (`services/execution/reference_resolver.py::REF_RESOLVERS`):
  - `ref_kind: "inventory"` → value is an **inventory id** (int); resolved via
    the RBAC-checked `InventoryService.get_inventory(id, username=…)`.
    `get-nautobot-devices` reads it when its `inventory_source` config is
    `"run_param"` (pointing at `inventory_param`), in place of the inventory
    selected in the step for that run. (A selected `inventory_id` is itself
    resolved live on every run — both go through
    `NautobotSourceService.resolve_saved_inventory_devices_by_id`.)
  - `ref_kind: "credential"` → value is a **credential vault name** (str);
    late-bound per triggering user (a private credential wins over a global one
    of the same name — see `credential_resolver._resolve_credential`). Every SSH
    step reads it when its `credential_source` config is `"run_param"` (pointing
    at `credential_param`).
  This is how one workflow definition serves many sites/teams: a schedule (or a
  manual run) supplies a different inventory id and credential name each time.
  Operators never type an id: the manual Run Inputs dialog renders an
  `ref_kind: "inventory"` attribute with `RunInputReferenceField`
  (`workflows/components/run-input-reference-field.tsx`) — a searchable list of
  active saved inventories by name (substring filter) that submits the numeric id
  (`Combobox` in `inline` mode so the dialog's scroll area doesn't clip it).
  `ref_kind: "credential"` has no picker there yet and falls back to a text box
  expecting the exact vault name (the schedule editor has a `Select` for both).
  Adding a new `ref_kind` (e.g. `nautobot_source`, `git_repo`) is one class +
  one `REF_RESOLVERS` entry plus the matching literal in `models/workflows.py`.
- **Where reference values are validated**: shape only in `resolve_run_inputs`
  (a positive int / a non-empty str — it is pure, no DB). Existence + access +
  type/expiry is `validate_reference_inputs`, called at **schedule-save**
  (`ScheduleService`, → 422) and again in `scheduled_trigger.dispatch` (→ failed
  run) so a broken reference can't slip through unattended.
- **Why not a canvas step**: a "request input" step feeding a downstream node
  alongside `get-nautobot-devices` doesn't work under today's connection rules.
  `frontend/src/lib/capability-types.ts`'s `isValidConnection` requires a
  **single edge's source** to satisfy a target node's **entire** `requires`
  list, so a node needing both `identity` (from an inventory step) and a new
  input capability could never be wired from two independent root nodes.
  Making the schema workflow-level instead of node-level sidesteps this.
- **Collection**: once a workflow is dispatched to Hatchet, only `run_id`
  crosses into `WorkflowRunInput` — nothing can be injected mid-run outside the
  existing durable-wait/event mechanisms (see "Wait & Run" under
  [Fan-out execution](#fan-out-execution) below). So values must be collected
  *before* dispatch:
  - **Manual trigger**: the builder's Run flow (`requestRun` /
    `WorkflowRunInputsDialog` in `workflow-builder-page.tsx`) prompts for
    values when `static_attributes` is non-empty, then passes them as
    `run_inputs` on `WorkflowRunCreate`.
  - **Scheduled (cron) trigger**: each `WorkflowSchedule` carries its own
    `run_inputs` bag (set in the Schedules app, `/schedules`), merged with the
    workflow's declared defaults by `scheduled_trigger.py::dispatch`. A required,
    default-less attribute the schedule doesn't cover still fails that run
    immediately (`status="failed"`, `error_category="configuration"`).
  - **Called by another workflow** (`trigger_type="workflow"`): the
    `start-workflow` step fills the target's inputs from its own configuration
    (`run_inputs`, plus the device list in the input a Get from User step reads) and starts it through
    `RunService.start_child_run`. Secret inputs are never supplied this way. See
    [Starting another workflow](#starting-another-workflow-start-workflow).
  - All paths validate/default-fill through the same pure helper —
    `services/execution/run_input_validation.py::resolve_run_inputs` — so a
    manual 400, a schedule-save 422, a scheduled run failure and a refused child run never disagree
    on what's valid.
- **Storage**: resolved values are persisted on `WorkflowRun.run_inputs`.
- **Making values usable by steps**: device-attribute resolution
  (`services/workflow_context/attribute_path.py::resolve_device_attribute`)
  and Jinja rendering (`workflow_steps/common/jinja_render.py::build_jinja_context`)
  are entirely device-scoped — they read `DeviceContext.attribute_bags`, not
  `WorkflowContext.metadata`. So `run_inputs` is seeded into a reserved bag,
  `run_input`, on **every device** by `StepRunner`
  (`services/workflow_context/run_inputs.py::seed_run_input_bag`, called from
  `StepRunner._seed_run_inputs` right after `_execute_and_persist_node` and
  `_execute_one_subgraph_node` — the two, and only two, places a step's
  outcomes are produced on the live Hatchet path; fan-out children inherit the
  bag for free since their initial context is a copy of the already-seeded
  inventory outcome). Once present, any existing `{bag.field}` expression
  reads it like any other bag — `{run_input.vlan_id}` in a Jinja template,
  `route-on-attribute`, `update-attribute`, etc. — with **no per-step wiring**.
- **`run_input` is a reserved bag name**, the same way `parsed` is: attempting
  to write to it via `update-attribute` raises a `ValueError`
  (`workflow_steps/common/attribute_write.py::_RESERVED_BAG_NAMES`), so a
  generic write can't silently overwrite what the operator supplied for the
  rest of the run.
- **Boolean values** are stored as native JSON booleans (not pre-stringified),
  so Jinja gets a real boolean for truthy checks. `resolve_device_attribute`
  still stringifies it the same way it does any other bag scalar — a Python
  `bool` renders as `"True"`/`"False"` (capitalized) — so a
  `route-on-attribute` condition matching a boolean-typed run input must
  compare against `True`/`False`, same as any other bag value today.

---

## Attribute path syntax: list filter segments

Every dotted attribute path (`route-on-attribute`'s `attribute_path`, Jinja
`{bag.field}` expressions, `update-attribute`, etc.) is resolved by
`services/workflow_context/attribute_path.py`. Paths are plain `.`-separated
segments (`nautobot.role.name`), with one piece of extra syntax for reaching
into a **list of dicts**: a segment of the form

```
<key>[<field>=<value>]
```

navigates to the list at `<key>`, then continues traversal from the **first**
item whose `<field>` stringifies to `<value>` — e.g.
`parsed.batfish_extract_facts.parsed.TACACS.TACACS_Servers[address=10.0.0.5]`
picks the one TACACS+ server dict whose `address` field is `"10.0.0.5"` out of
a list. Rules:

- `<field>` is itself resolved via the normal dotted-path traversal *inside
  each item*, so it may be a nested sub-path (e.g. `endpoint.ip=10.0.0.5`) —
  but it must resolve to a scalar; a `<field>` that resolves to a nested
  dict/list on an item is never considered a match.
- Only **one** `key=value` filter per segment — there is no `AND` of multiple
  conditions. A segment `<key>[<n>]` (digits only, e.g. `serial[1]`, `parsed[0]`)
  selects the list item at that 0-based position instead.
- Only the **first** matching item is returned. If more than one item shares
  the same `<field>` value, the filter is not a safe way to distinguish them.
- `<value>` is compared via plain string equality (`str(candidate) == value`),
  so a numeric or boolean field must be matched against its stringified form
  (e.g. `port=49`, not `port=49.0`).

### Placeholders inside a selector

The text inside a `[...]` selector may be a `{other.path}` placeholder that is
resolved against the same device before the path is traversed
(`expand_path_placeholders` in `attribute_path.py`, applied by
`resolve_device_attribute`, `resolve_device_attribute_state` and
`resolve_device_value`), so one path can pick a list item by a value held elsewhere:

```
parsed.k.show version.parsed[0].serial[{virtual_chassis.stack_index}]
parsed.k.show switch detail.parsed[switch={virtual_chassis.position}].role
parsed.k.show switch detail.parsed[mac_address={virtual_chassis.mac}].role
```

- Placeholders are accepted **only inside `[...]`** (not as a key name) and are
  resolved with `reveal_secrets=False`; a sealed secret is never embedded. A value
  containing `[`, `]` or `=` is rejected (it would change the path's shape, e.g. turn
  an index into a field filter). Placeholders may nest to any depth:
  `…show switch.parsed[mac_address={…show version.parsed[0].mac_address[{x.i}]}].role`.
- An unresolved, malformed or rejected placeholder makes the whole path unresolved
  (`None` / `ABSENT`), the same as a missing key — `update-attribute` then skips the
  write rather than failing the device.
- A `[n]` index needs a numeric value; a non-numeric one simply does not resolve.
- In `update-attribute` template mode, `{...}` may enclose a path that itself has a
  placeholder in a selector: `{parsed.k.show version.parsed[0].serial[{x.i}]}`. Braces
  are only accepted inside a selector there, so JSON-like text such as
  `{"k": "{x.y}"}` still expands just `{x.y}`.
- Not supported: placeholders in a **destination** path, and nested `{…}` inside the
  `{path | default('x')}` value expressions used by steps such as Update Device. For
  anything more complex use `render-jinja-template`.

The **attribute path picker** (the "Browse attributes" button on
`route-on-attribute`'s config panel, in
`frontend/src/components/features/workflow-steps/shared/attribute-path-picker.tsx`)
discovers real paths from a workflow's most recent run and generates this
filter-segment syntax automatically: for a list of dicts it infers a
discriminating field (a scalar field present on, and uniquely identifying,
every item — preferring conventional names like `name`/`id`/`address`) via
`services/workflow_context/attribute_path_discovery.py::infer_discriminator_key`,
and emits one ready-to-use path per item. When no field can uniquely identify
every item, the picker still offers a best-effort filter path but flags it
with a warning rather than silently picking an ambiguous one.

---

## Secret-valued attributes

Some attribute bag leaves — currently `tacacs.shared_secret` and the nested
`ise.tacacsSettings.sharedSecret` — hold sensitive values (TACACS+ shared
secrets) that must never appear as cleartext outside the live run. The
contract lives in `backend/services/workflow_context/secret_fields.py`:

- **`seal_secret(plaintext)`** — encrypt a value into a sealed envelope
  (reuses the same Fernet key material as credential-table encryption —
  `CREDENTIAL_ENCRYPTION_KEY`, falling back to `SECRET_KEY`; see
  `backend/.env.example`) before writing it into `DeviceContext.attribute_bags`.
  Every write site that produces one of `SECRET_BAG_PATHS` must seal it —
  never `set_device_attribute` a raw string at a known secret path. No new
  key is provisioned for this — rotating `CREDENTIAL_ENCRYPTION_KEY` also
  invalidates any secret already sealed under the old value, the same way it
  would invalidate a stored credential; `unwrap_secret` raises `ValueError`
  in that case, which the calling step must let propagate as a failure
  rather than treating the secret as absent.
- **`unwrap_secret(value)`** / **`is_sealed_secret(value)`** / **`secret_is_present(value)`**
  — decrypt, detect, and presence-check a sealed envelope respectively.
  `secret_is_present` never decrypts — use it for "does this device already
  have a key" checks.
- **`redact_secrets_in_data(data)`** — deep-copies a serialized context dict
  and replaces `SECRET_BAG_PATHS` leaves / any sealed envelope with the
  literal `***REDACTED***`. Applied at every boundary that persists or
  displays a run: `StepRunner._serialize_outcomes`, the Hatchet fan-out merge
  path (`hatchet/workflows/workflow_run.py::_aggregate_and_persist`), and
  `log-attributes`'s `build_context_snapshot`.
  Inside a run segment (`StepRunner.execute_all` / `resume_after_join` /
  `execute_subgraph` run under `run_secret_scope`) it also scrubs, by exact
  match and in free text, every cleartext secret of 8+ characters that was
  unwrapped via `unwrap_secret` or read through `CredentialsService.get_decrypted_*`
  during that segment (W6). A secret that never passed through those calls
  (typed into a template) is still unknown to the redactor.

**`resolve_device_attribute(device, path, *, reveal_secrets=True)`**
(`workflow_steps/common/attribute_path.py`) is the shared read path and
decides whether a sealed leaf gets decrypted for the caller:

- **Trusted, intentional consumers** (Jinja rendering via `build_jinja_context`;
  `update-ise-tacacs-key`/`add-to-ise`'s field-expression resolution) keep the
  default `reveal_secrets=True` — they need the cleartext to do their job
  (build a TACACS+ config line, send an ISE API payload).
- **Generic / bulk steps** that write a *resolved* value into a *new* bag
  location — `update-attribute`, `log-message` — must pass
  `reveal_secrets=False`. A `False` call returns `REDACTED_PLACEHOLDER`
  instead of cleartext; `update-attribute` treats that as a hard `ValueError`
  (it must not create a second, unsealed copy of a secret at an arbitrary
  path). Any new step added later that resolves an attribute and copies the
  result elsewhere must default to `reveal_secrets=False` unless it is one of
  the documented trusted consumers above.

**Known limitation — redaction is shape-based, not content-based.**
`redact_secrets_in_data` only recognizes secrets by the sealed-envelope
marker or by the fixed `SECRET_BAG_PATHS` dotted paths under
`attribute_bags`. If a step resolves a secret to cleartext (`reveal_secrets=True`)
and then writes that cleartext into a *differently shaped* output — a diff
entry, a filtered list, a free-text outcome message — it becomes a bare
string neither mechanism recognizes, and it will **not** be redacted at
persist time. Do not do this. If a new step legitimately needs to consume a
secret, keep the consumption in-memory for that call only (as
`render-jinja-template` and the ISE-update steps do); never copy the
unwrapped value into a plain attribute bag, log line, or step summary.

Rendering a secret into a stored artifact via `render-jinja-template` →
`store-artifact` remains an explicit, documented operator choice, not a bug —
it is outside the scope of the in-run context/DB protection above. A workflow author can render
any credential they can use into a stored artifact, and `ssh`/`generic`/`shared_secret` credentials
are equally reachable by other means: see "Workflow authors hold the cleartext of global
credentials" in `doc/SECURITY-NOTES.md` and the trust model in `SECURITY.md`.

---

## Fan-out execution

An **inventory step** (`get-nautobot-devices`, `get-virtual-chassis`, `get-git-devices`,
`get-ise-devices`, `get-catalyst-center-devices`, `get-from-list`, `get-from-user`) may enable
**fan-out**: instead of running the whole workflow once with every device sharing a
single context, each device — or each chunk of devices — is processed as an independent
Hatchet **child workflow**. This parallelises per-device work and isolates failures.

### What may sit next to a fan-out branch (rules R1-R3)

A workflow with an enabled fan-out step is valid only if, with `R` = everything downstream of
the fan-out step: **R1** every other step outside `R` runs before it (same or earlier wave) —
a step that is neither below the fan-out step nor before it would never execute; **R2** every
step in `R` receives input only from `R` or the fan-out step itself (branches only get the
fan-out step's devices); **R3** at most one step has fan-out enabled. The rules are checked at
save time (`WorkflowService`, HTTP 400 naming the offending steps) and in the pre-run
validation (`WorkflowValidationService`, Tier 1 error, so runs and schedules refuse a legacy
workflow with the same message). Implementation: `services/execution/fan_out_topology.py`.

**Child vs parent.** A fan-out child walks the resolved graph, like the parent. Once a step
*raised* inside a child, the child's remaining steps are skipped (the same hard stop as the
main walk); a *reported* device failure still lets failure-handler branches run. Branches may
share `DeviceContext` objects because every attribute writer copies on write; CI sets
`MANUS_STRICT_CONTEXT=1`, which makes the runner fail a step that mutated its input.

### How it is configured

Fan-out lives in the inventory step's `pluginConfig.fan_out`:

```json
{
  "enabled": true,
  "mode": "per_device",   // "per_device" (1 child per device) or "chunked"
  "chunk_size": 1,         // devices per child when mode == "chunked"
  "max_concurrency": 0,    // 0 = unlimited, 1 = sequential, N = N children at a time
  "approval": {            // optional — see "Wait & Run" below
    "enabled": false,
    "batch_size": 1,
    "first_batch_auto": true
  }
}
```

The inventory executor copies these values into `context.metadata["_fan_out"]` via the
shared `workflow_steps/common/fan_out.py::build_fan_out_metadata` helper when `enabled`
is true (all seven inventory steps — `get-nautobot-devices`, `get-virtual-chassis`, `get-git-devices`,
`get-ise-devices`, `get-catalyst-center-devices`, `get-from-list`, `get-from-user` — call this one helper; do not duplicate the
sanitisation inline in a new inventory step).

### Wait & Run — user-approved batching

Setting `fan_out.approval.enabled: true` turns the automatic chunking above into a
**canary rollout gate**: dispatch groups (devices in `per_device` mode, chunks in
`chunked` mode) are batched into sets of `approval.batch_size` groups, and the run
**pauses** after each batch until an operator clicks **Run next batch** or **Run all
remaining** in the UI (`POST /runs/{id}/approve-batch` / `/approve-all`). This is how a
config change (e.g. a TACACS+ key rollout) gets applied to 10 devices, reviewed, then
released to the next 10, instead of all devices at once.

- Implemented entirely in the parent orchestration
  (`hatchet/workflows/workflow_run.py::_dispatch_children`) — **not** a canvas step.
  A step executor only ever sees one child's device subset and cannot gate the
  parent's batch-dispatch loop; see the design rationale in doc/WAIT-AND-RUN.md §2.
- `approval.first_batch_auto` (default `true`) skips the gate before the very first
  batch — the initial **Run** click implicitly approves it.
- The gate is a durable wait (`ctx.aio_wait_for_event` + `hatchet.event.push`, keyed
  via `services/execution/run_events.py`) on a `workflow-run.{uuid}.batch.{n}` event.
- `WorkflowRun.approval_state` (JSON column) carries batch progress, device counts, and
  the next batch's device names while `status == "paused"`; it is cleared once the run
  reaches a terminal status.
- Finished batches are aggregated into `WorkflowStepResult` immediately
  (`_aggregate_and_persist(..., final=False)`), so an operator can inspect a batch's
  per-device outcomes while later batches are still gated.
- The fan-in node still runs exactly once after the *last* batch, preserving the
  one-pull/one-commit/one-push guarantee described below.

Full design, data model, and edge cases: **doc/WAIT-AND-RUN.md**.

### Execution flow

```
WorkflowExecution (parent Hatchet task)   hatchet/workflows/workflow_run.py
  └── StepRunner.execute_all()
        ├── runs steps topologically until …
        └── the inventory step emits _fan_out.enabled
              → execute_all RETURNS a FanOutSignal (with join_node_id, if any)
                and STOPS. Downstream steps DO NOT run in the parent yet.

  Phase 2: _dispatch_children()
        └── split devices into groups (per_device or chunked)
              → one DeviceGroupExecution child per group (bounded by max_concurrency)

  DeviceGroupExecution (child Hatchet task)  hatchet/workflows/device_group_execution.py
        └── StepRunner.execute_subgraph()
              → runs the CHILD BRANCH only — nodes downstream of the inventory step
                MINUS the fan-in node and everything after it (StepRunner._child_node_ids)
                — for that group's device subset, WITHOUT writing WorkflowStepResult rows
                (progress goes to its WorkflowRunDeviceGroup row instead — see below).

  Phase 3: _aggregate_and_persist()
        └── merge_fan_out_contexts() folds each child's per-node outcomes together,
            writes one WorkflowStepResult per child-branch node, and RETURNS the
            merged per-node contexts.

  Phase 4 (only when a fan-in node exists): StepRunner.resume_after_join()
        └── seeds the merged child outcomes (+ the inventory outcome), then runs the
            fan-in node and everything downstream of it ONCE on the fanned-in context,
            writing those WorkflowStepResult rows on the parent run.
```

Key consequence: every step in the **child branch** runs once per child (once per device
in `per_device` mode, once per chunk in `chunked` mode) on a single-device/single-chunk
context. Every step **at or after the fan-in node** runs exactly **once** on the merged
context. **Without** a fan-in node, the child branch is the entire downstream subgraph and
the parent never re-executes anything — so `store-artifact`/git steps would run once per
child (see the safety table below).

### Live progress while a run executes

The UI polls `GET /runs/{id}` every 2s, and that endpoint only reads committed rows. Two
things used to be invisible until they finished, and are now persisted as they happen
(both best-effort — a failing progress write is logged and never fails a device run):

- **Fan-out child progress** — `WorkflowRunDeviceGroup` (`core/models/runs.py`), one row
  per group, keyed `(run_id, child_index)`. The parent pre-creates them as `pending` in
  `_dispatch_children` (`fan_out_dispatch.py::_precreate_device_groups`); each child marks
  its row `running` and, through `DeviceGroupProgressSink`
  (`services/execution/step_runner/progress.py`, passed to `run_subgraph(progress=…)`),
  records `node_states` (`node_id → running | success | partial | failed | skipped`).
  It ends `success`/`partial`/`failed`, or `failed` with `error_message` if the child
  crashed. Children still write **no** `WorkflowStepResult` rows — the parent aggregates
  those as before. `RunService` returns the rows as `device_groups` on the run detail, and
  the frontend overlays them on still-`pending` child-branch step rows
  (`utils/live-step-progress.ts::deriveLiveStepProgress`, e.g. "3/12 groups done · 2
  running") and lists them in the **Device groups** panel. A step the parent already
  persisted is never overridden.
- **In-step events** — `WorkflowRunEvent`, an append-only log (capped at
  `MAX_EVENTS_PER_RUN` = 2000 per run, with one `truncated` marker) served incrementally
  by `GET /runs/{id}/events?after_id=&limit=` (permission `workflow_runs:read`).
  `StepRunner` binds a `RunEventContext` (`run_id`, `node_id`, `child_index`) around each
  node (`services/execution/run_events_reporter.py`);
  `DeviceSessionPool.run_on_device` reads it **before** hopping to its thread executor
  (contextvars don't cross `run_in_executor`) and passes an explicit `on_event` callback to
  `NetmikoDeviceSession.connect`, which reports `connect_attempt`, `connect_retry`,
  `connected`, `connect_failed`, `auth_failed` and `setup_rejected` (the device refused a session-setup command such as `terminal length 0`; a later command timeout is then classified `permission_denied`). Emission uses its own short-lived DB
  session (it runs on a worker thread). No executor needs to know about it. Auth-failure
  events deliberately carry no exception text, since it can echo credentials.

To report more from a step, emit through `emit_run_event(current_run_event_context(), …)`
rather than writing to the run's `Session`.

### The fan-in (rejoin) node — `fan-in`

The **Fan In** node (`store-artifact`/git-safe rejoin) marks the boundary where the
fanned-out branches converge back into a single execution path:

```
inventory (fan_out on) → get-configs → render → [FAN IN] → store-artifact(git) → git-push
        │                └──── runs once PER CHILD ────┘    └──── runs ONCE in parent ────┘
        └── children stop before the fan-in node; parent resumes after the rejoin
```

- **Contract** (`registry.yaml`): `artifact_type: control_flow`, `requires: [identity]`,
  `produces: []`, `consumes: []`, `outcomes: [success]`. It passes every device capability
  through unchanged, so `running_config` / `parsed` / etc. remain available to post-join steps.
- **Executor** (`workflow_steps/fan_in/executor.py`) is a near pass-through: device merging
  is done by the orchestration layer (`merge_fan_out_contexts` in `_aggregate_and_persist`),
  not by the step. The executor just stamps `metadata["{node}.fan_in"] = {"device_count": N}`
  and emits one `success` outcome.
- **Placement:** put per-device compute (`get-device-configs`, `run-command`,
  `render-jinja-template`) **before** the fan-in node and git/store steps **after** it, so
  exports commit and push exactly once over all devices.
- **Scope (v1):** one fan-in node downstream of the fanned inventory step; the runtime picks
  the first `fan-in` node it finds (`StepRunner._find_join_node_id`). No nested fan-out.
- **Partial failure:** failed devices flow through the merge with `FAILED` status; the fan-in
  and post-join steps still run on the device union (proceed-with-survivors). The per-step
  result may be `partial`. The run is also `failed` when a post-join step raises, when a
  step's own outcome fails for every device it saw, or when a step downstream of it is
  `skipped` because every device that could have reached it was lost upstream (see
  **Run and step status** below) — not only on a raised exception.
- **`stop-here` cannot sit inside the fanned-out branch:** it truncates the graph via
  `StepRunner.load_execution_graph` (`resolve_stop_here` in
  `services/execution/step_runner/graph_resolution.py`), but a fan-out child
  (`hatchet/workflows/device_group_execution.py`) reads the raw canvas directly, not
  through `load_execution_graph` — so a `stop-here` node between the inventory step and
  its Fan In would silently do nothing there instead of truncating the run.
  `WorkflowService` rejects this shape at save time
  (`_validate_stop_here_not_in_fan_out`). `stop-here` is fine anywhere outside a
  fan-out branch, including after a Fan In node.

### Run and step status

`WorkflowRun.status` is not a passive rollup of `WorkflowStepResult.status` values — it is
computed once, at the end of the topological walk (`StepRunner.run_node_in_sequence`,
called from `_run_steps_until_fan_out_or_done` / `resume_after_join`, and mirrored for
fan-out aggregation in `hatchet/workflows/workflow_run.py::_aggregate_and_persist`). A run
ends up `"failed"` when any of the following happened, not only when an executor raised:

- an executor raised (existing behaviour — all remaining nodes are marked `skipped`);
- a step's own outcome has zero successful devices and at least one failed device
  (`WorkflowStepResult.status == "failed"`), even if nothing downstream depended on it;
- a step was marked `"skipped"` because every device that could have reached it was lost
  to a real upstream failure (`StepRunner._blocked_by_upstream_failure`) — the step is
  never invoked in this case, so it doesn't collapse into a misleading trivial `"success"`
  with zero devices processed.

This last case matters because most executors guard `if not context.devices: return
[StepOutcome(name="success", context=context)]` — without the pre-check, a step
downstream of a fully-failed step would silently report `"success"` for having done
nothing. The pre-check only fires when the step's registry entry `requires` device
identity (`Capability.IDENTITY`) **and** there is actual failure evidence upstream (a
parent's `failure` outcome has devices, or the parent was itself blocked) — an inventory
step that legitimately matches zero devices (no filter results, nothing errored) is left
alone and still reports a trivial `"success"`, so a run isn't marked failed just because a
filter matched nothing. A node wired to a failing step's own `failure` handle (e.g. an
on-failure notification branch) is unaffected and still runs normally — only the branch
that actually lost its devices gets skipped.

**Shared error sink instead of one notify node per step.** Wiring *many* steps'
`failure` handles to one downstream node is ordinary fan-in — nothing limits how many
edges converge on a target handle. `merge_workflow_contexts` (used when branches
converge) unions the devices from each converging `failure` outcome and dedupes
`DeviceContext.errors` by `(node_id, step_id)`, so the shared node runs once with the
union of every device that failed anywhere upstream, each still carrying its own
root-cause `DeviceError`. The `notify-on-error` step (`workflow_steps/notify_on_error/`)
is built for this: it writes one notification per accumulated error on each device, using
a dedicated `{error.step_id}` / `{error.node_id}` / `{error.code}` / `{error.message}`
placeholder namespace resolved by `resolve_device_attribute`'s optional `error` param
(`services/workflow_context/attribute_path.py`) — populated only when a step explicitly
passes one `DeviceError` from `device.errors` per render call, so it's `None`/absent for
every other step's placeholder templates. Place the sink after the last step whose
failures it should catch, since a node only runs once its predecessors on that handle
have converged.

### Fan-out merge (`services/workflow_context/merge.py`)

`merge_fan_out_contexts` folds disjoint child contexts back together:

- **devices** — plain union (children own disjoint device sets).
- **metadata lists** (e.g. `{node}.stored_artifacts`) — concatenated across children.
- **metadata scalars/dicts** (e.g. `{node}.git_export`) — **first child wins** on
  conflict, silently. A per-run aggregate value cannot be reconstructed this way.

### Writing concurrency-safe steps

When you author a step, assume it may run concurrently against the **same external
resources** via either of two independent mechanisms:

- **Fan-out** — many `DeviceGroupExecution` children, potentially on different Hatchet
  workers (cross-process — nothing in this process can lock across that boundary).
- **Independent branches in the same run** — two canvas branches with no dependency on
  each other run concurrently within one `StepRunner`'s topological-generation walk (see
  "Independent branches run concurrently" in `doc/HOWTO_BUILD_WORKFLOWS.md`). Same
  process, same run, but still genuinely concurrent — a step that assumed "nothing else
  touches this resource while I run" because of graph ordering alone no longer gets that
  for free unless a real dependency edge (or a join point) enforces it.

A step is concurrency-safe when it:

- writes only to **per-device-unique** destinations (e.g. a `filename_template` keyed on
  `{device.name}`), and
- holds **no shared mutable external state** that multiple concurrent callers — fan-out
  children or sibling branches — mutate at once.

| Step kind | Concurrency safe? | Why |
|-----------|---------------|-----|
| `get-device-configs`, `run-command`, `run-catalyst-center-command`, `get-catalyst-center-configs`, `get-catalyst-center-details`, `get-catalyst-center-topology`, `get-catalyst-center-health`, `merge-config`, `get-nautobot-attributes`, `get-device-location`, `get-virtual-chassis`, `split-virtual-chassis`, `render-jinja-template`, `log-message`, `route-on-attribute`, `generate-password` | ✅ | Per-device compute, no shared mutable sink. |
| `git-status` | ✅ | Read-only inspection (plus an optional `git fetch`) under the per-repository lock, so concurrent callers are serialised, not corrupted. Its result is per repository, not per device — inside a fan-out branch it re-checks the same repo once per child, so prefer a single check before the fan-out inventory step's children or after a Fan In. |
| `start-workflow` | ⚠️ | Starts one run for all devices it receives, or one per device (`max_runs`), and optionally polls them for up to 600 s. Two concurrent callers start two sets of runs, so inside a fan-out child it starts runs per child, each waiting in its own worker slot: place it before the fan-out or after a **Fan In**. See "Starting another workflow: `start-workflow`" below. |
| `send-mail` | ⚠️ | Sends one email per execution and holds no shared state, so concurrent callers never corrupt anything — but inside a fan-out child branch it sends **one mail per child**. Place it after a **Fan In** node (or at the end of a non-fanned workflow) for one mail per run. Mail is sent only through the SMTP server an administrator configured under Settings → Mail (server, port, security, login credential and sender address are not step settings; the admin's `allowed_recipient_domains` apply). The step config keeps `to`, `subject` and `body`. |
| `add-nautobot-metadata` | ✅ | Writes shared Nautobot reference data (a Location / Device Type), but as get-or-create: an existing object is reused, a duplicate-key error from a concurrent creator is resolved by re-reading it, and devices resolving to the same object share one call within a step run. |
| `store-for-report` | ✅ | Appends rows to the report tables keyed by (dataset, device name, collection), so fan-out children and sibling branches that handle disjoint devices never touch the same rows and no Fan In is needed. The same step writing a dataset for the same device again in a run (retry, loop) replaces its earlier rows; a **different** step writing the same dataset for the same device fails that device (`node_id` is recorded per row): put all fields of a dataset into one step, or use one dataset per step. A path that matches nothing stores `null` (right for an optional attribute, but also what a mistyped path does): when a field is empty for every stored device in `device` mode, the step stays `success` and its summary names the field (`field(s) 'ip' had no value for any of 2 device(s); check the attribute path`). Rows are never deleted by the step; see `doc/REPORTS.md`. |
| `store-artifact` → `destination: filesystem` | ⚠️ | Safe **only** if `filename_template` is device-unique. A fixed name or colliding `{run.timestamp}` makes concurrent callers overwrite/race. |
| `store-artifact` → `destination: git`, `git-clone`, `git-pull`, `git-push`, `open-change-request` | ⚠️ | All open **one shared on-disk working tree per git repository** (`load_git_repository` → single `path`). A per-repository advisory lock (`services/git/repo_lock.py`, Redis `SET NX EX`; fail-soft only when Redis is unavailable, a lock still held after the 90 s acquire timeout fails the step) serialises concurrent callers against the *same* `GitRepository` — whether two runs, fan-out children (cross-process), or two independent sibling branches in one run (same process) — so the working tree itself is **not** corrupted. It does **not** make two concurrent callers collapse into one logical operation, though: each still opens its own commit (and, for `open-change-request`, its own branch/change-request row), which is rarely what you want. Place git-touching steps after a **Fan In** node (fan-out) or wire an explicit dependency edge (independent branches) so exactly one export/commit/change-request comes out, not N. |

**Guidance for git-backed exports:** place a **Fan In** node between per-device fan-out
branches and the git/store steps (one pull, one commit, one push; `max_concurrency: 1`
only serialises children and still produces N commits, so it is not a substitute). For two
independent *non-fan-out* branches that both need to touch the same git repository in one
run, wire an explicit dependency edge between them (or route both through a shared step
first) instead of letting the canvas leave them as true siblings — the lock stops
corruption either way, but still produces N commits/change-requests if you don't.

> If you add a step that mutates a shared external resource, either require it to sit after
> a join point / explicit dependency, document its concurrency behaviour in `registry.yaml`,
> and/or prefer per-device-unique writes.

### Starting another workflow: `start-workflow`

`start-workflow` (display name "Run Workflow", `artifact_type: control_flow`, outcomes `success` /
`failure`) starts another workflow as a **run of its own** and optionally waits for it. Motivating
case: back up the running config before a change.

- **Devices arrive like they do for a schedule or a manual run: as a declared run input.** A target
  that wants devices has a **Get from User** step; its `device_param` is a text run input holding one
  `name`, `ip` or `name,ip` line per device. `devices_input` names that input; the step fills it with
  one `name,ip` line per device it received (`_device_line`: bare primary IP, a name containing a
  comma or line break is replaced by the IP; a device with neither fails with `no_device_identity`).
  With no `devices_input` the target is called without devices. No engine special case, nothing in
  `WorkflowRun.device_ids`: the same workflow can be run by hand, scheduled, or called.
- **The form is generated from the target's declared inputs** (the same fields the schedule editor
  shows, `ScheduleParameterFields`): a saved-inventory reference gets the inventory picker, which is
  how "back up this saved inventory" works, independent of the caller's devices. The panel
  auto-selects the target's only device input and shows required-without-default inputs, inputs the
  target no longer declares, and secret inputs.
- **Run modes.** `run_mode: "all_devices"` (default) starts one run for all devices and routes them
  together. `"per_device"` starts one run per device and routes **each device by its own run**.
  `max_runs` (default 25, 1-200) caps the runs; more groups than that raise `ValueError` before
  anything is started, and the builder warns (louder when the calling workflow fans out, where the
  step would run in every child).
- **Wait is bounded.** `wait` (default on), `wait_seconds` (default 300, 5-600),
  `poll_interval_seconds` (default 5). One shared budget polls all started runs. It is a plain poll,
  like `check-nautobot-job`: an executor has no Hatchet `DurableContext`, so the wait holds a worker
  slot and is lost if the worker restarts (the runs are not). `wait: false` only dispatches and
  reports `success`.
- **What counts as success.** The run is `success`, the enabled Get from User step that reads
  `devices_input` has a `success` step result (else `child_run_not_applied`: a disabled or skipped
  step means nothing was done for the devices), and no step is `failed` or `skipped` or, unless
  `allow_partial`, `partial`. A failed or cancelled run, a partial result, a timeout
  (`task_timeout`, retryable; the run keeps going) or an unreachable engine route the device through
  `failure`. Configuration refusals (no access, no `workflows:execute`, recursion, bad run inputs,
  target without the input) `raise` `ValueError`.
- **No secret inputs.** `run_inputs` lives in the saved canvas as plain JSON, while a `secret` run
  input is only sealed when a run is created. A step may therefore not give a value for a secret
  input of its target: `WorkflowService` rejects the save (HTTP 400, names only the input, never the
  value; `services/workflow/child_run_inputs.py`) and the executor rejects workflows saved before
  that rule. A workflow with a required secret input cannot be started by this step; it uses
  credential references with a default.
- **Authority and loops.** A run starts as the parent's triggering user (`require_child_target`:
  workflow visibility and `workflows:execute`, the bar a manual trigger has). A workflow cannot start
  itself or any ancestor, and a chain is at most `MAX_CHILD_RUN_DEPTH` (3) deep
  (`RunService.start_child_run`). The guard reads `WorkflowRun.ancestor_workflow_ids`, the ancestors'
  workflow ids copied onto every child, **not** the `parent_run_id` link: that is cleared
  (`ON DELETE SET NULL`) when a finished ancestor is deleted or purged, which would otherwise let a
  still-running descendant start its ancestors again without a depth cap. A run that is no longer
  active (cancelled, failed, finished) cannot start children.
- **Cancel.** Cancelling the parent (`RunService.cancel_run`) cancels its still-active child runs
  (`RunService.cancel_child_runs`, at any depth and **through finished children**: a child started
  without waiting, or one that hit its wait timeout, can be done while its own children still run),
  and so does finalising an interrupted parent
  (`RunLifecycleService.fail_interrupted`: worker crash, engine cancel, the reaper), because nobody
  is left to gate on or judge them. `start_child_run` closes the race with a cancel in progress: it
  refuses an inactive parent and, after creating the child, looks at the parent again and cancels
  the child if the parent ended meanwhile (cancel marks the parent, then sweeps once). A parent that
  simply fails on a later step does **not** cancel a
  child it started: that run, a backup for instance, is allowed to finish. A waiting step stops
  waiting when its own run is cancelled.
- **Result.** Each device gets `attribute_bags[bag_name]` (default `child_run`) =
  `{run_id, workflow_id, status, waited_seconds}`.

### Change requests (CI/CD pipeline)

`open-change-request` is a persistent-artifact step that ends a *stage run*: it commits
the rendered configs to a per-change git branch, pushes it, stores a diff, and records a
`ChangeRequest` row awaiting review. Approval (a UI click or a signed git webhook)
dispatches a **separate** deploy run — an ordinary workflow that starts with
`from-change-request`, which checks out that branch pinned to the reviewed commit. The long review is a DB
row, not a Hatchet pause (the `execute_steps` task is capped at 24 h). Full spec, data
model, webhook, and API: [`doc/CICD_PIPELINE.md`](./CICD_PIPELINE.md).

---

## Adding a new step — checklist

1. **Backend package** — create `backend/workflow_steps/{step_id}/`:
   - `__init__.py` (empty)
   - `executor.py` with `async def execute(*, config, context, run, artifact_service, node_id, device_sessions)`
     (**omit for canvas decorations** — see [Canvas decorations](#canvas-decorations))
   - `config.py` with `def get_config() -> dict` (if the step has configuration)
   - `models.py` with step-specific Pydantic models (if needed)

2. **Logging** — add a `logger.info(...)` line when the step starts and another when it
   finishes (see [Logging](#logging--start-and-finish-log-lines-are-required) above).
   Skip for `executable: false` decorations.

3. **Dispatch table** — add one import and one entry to `services/execution/step_registry.py`
   (skip for decorations)

4. **Registry** — add an entry to `workflow_steps/registry.yaml`. For decorations set
   `executable: false`, `artifact_type: canvas_decoration`, and empty outcomes.

5. **Frontend ConfigPanel** — create `frontend/src/components/features/workflow-steps/{step-id}/index.tsx`
   (config UI only; canvas rendering is shared — see [Canvas node appearance](#canvas-node-appearance),
   except decorations which use custom RF node types)

6. **UI registry** — add an entry to `frontend/src/lib/plugin-ui-registry.ts`

7. **Canvas icon (optional)** — add a `nodeIconsByKind` entry in `workflow-node.tsx` /
   `step-visuals.ts` when the default `artifact_type` icon is not appropriate; do not
   add a custom node render branch (except decorations)

8. **Fan-out review** — confirm the step is fan-out-safe (see [Fan-out execution](#fan-out-execution)).
   If it writes to a shared external resource, make the write per-device-unique or
   document the constraint. N/A for decorations.

9. **Secret handling** — if the step writes a credential/secret-like value into
   `DeviceContext.attribute_bags` (a TACACS+ key, an API token, etc.), seal it with
   `seal_secret()` before writing — never `set_device_attribute` a raw string at a
   known secret path. If the step reads an attribute value and copies the resolved
   result elsewhere (not just consumes it in-memory for one call), resolve with
   `reveal_secrets=False` and fail closed on a redacted read, unless the step is one
   of the documented trusted consumers (see [Secret-valued attributes](#secret-valued-attributes)).
   N/A for decorations.

10. **Credential type registration** — if the step has a `credential_reference` config
    field, register which vault credential type it resolves, or the pre-run validator
    assumes `ssh` and rejects a Basic Auth (`generic`) credential with
    `credential_reference_wrong_type`. Add the step id to `_GENERIC_STEP_KINDS` (or
    `_SHARED_SECRET_STEP_KINDS`) in `backend/services/workflow/workflow_validation_service.py`
    **and** the matching set in
    `frontend/src/components/features/workflows/utils/workflow-import.ts` — the two are
    hand-mirrored. Leave both alone only for SSH-credential steps (the default). Never put
    the username/password in the step config; reference the vault credential by name.
    N/A for decorations.