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

> **Step aliases (AI assistant).** Administrators can map a nickname to a step `id` under
> Settings → AI Assistant → Assistant glossary → "Workflow step aliases"
> (`doc/ai_integration/AI_ASSISTANT.md`, "Workflow step aliases"). An alias is stored as the
> step's `id` and re-checked against this registry on every lookup: removing, disabling or making
> a step non-executable, or giving another step an `id` or `name` equal to the alias word, makes
> the alias *stale* (the assistant ignores it and falls back to `list_steps`). `id` is immutable
> for the same reason; rename a `name` freely, but delete or re-point the aliases of a step you
> remove.

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
| `run`              | `WorkflowRun`         | ORM instance — `require_session(run, step_id)` for DB  |
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
stale copy; a stale read is recorded as a warning event). `refresh=False` skips the pull and reads the local copy under the same lease (only `enrich-attributes` passes it, via `refresh_repository`; see its section for why that is deliberate). Never keep the path after the `with` block. The switch is
offered by `upload-binary`, `read-from-file`, `read-config`, `enrich-attributes`, `get-from-config`, `batfish-init-snapshot` and
`batfish-validate-facts`; `set-default-attributes` and `get-git-devices` still pull strictly.

Where the table is applied (CF-07): `upload-config`, `add-to-nautobot` (interface/IP/prefix/virtual
chassis problems fail the device and keep the created id; a failed pre-flight check creates nothing), `batfish-init-snapshot` (a snapshot from
fewer devices than selected fails unless `allow_partial_snapshot`; skipped devices leave through the
new `failure` handle), `batfish-validate-facts` (empty expected facts fail the device),
`open-change-request` (identical configs leave through the new `unchanged` handle, no change request),
`route-on-attribute` (an unmatched device leaves through `failure`; route names `success`/`failure`
are reserved), `update-attribute` (a sealed source in regex or template mode, a selector into a bag of another shape
or an unexpected error fails that device through `failure`; missing required fields fail the step once, at
parse time), `list-contains` (a sealed `value` fails the device, `value_is_secret`), `start-nautobot-job`
(a parameter that points to a sealed secret fails the device; coercion errors never repeat the value),
`compare-data` / `route-on-content` (several exportable items fail the device with
`ambiguous_match`), `route-on-content` (the matched text is stored only with `store_matched_text: true`, off by default, and then passed through the config-secret redactor), `decrypt-attribute` (a sealed source fails the device, `source_sealed`), `compare-aci-subnets` (`namespace` is not needed with `namespace_from_vrf`), `merge-content` (nothing to merge fails the device; repeated `json_merged` keys
become `<key>#2`), `config-to-attributes` (devices without parsed data fail), `get-ise-devices`
(names ISE does not know leave through `failure`).

### Behaviours that are on purpose

- **A git step that fails still emits an (empty) outcome.** `git-clone`, `git-pull`, `git-push`, `git-status` and
  the other git steps mark themselves failed through their `failure` handle with the structured cause; a
  device-agnostic successor wired to `success` still runs on an empty context. Wire the `failure` handle where
  that matters.
- **`get-nautobot-attributes` replaces the whole `nautobot` bag** of a device with what it fetched; a step that
  wrote `nautobot.*` keys earlier must run after it, not before.
- **`config-to-attributes` structure**: the five source formats (`cisco_config_parser`, `genie`, `batfish`, `catalyst_details`, `aci_details`) are one table, `workflow_steps/config_to_attributes/formats.py` (`SOURCE_FORMATS`): where the upstream entry sits, the interface mapper, optional device fields, redundancy note and the two ACI hooks. A new format is one entry. `attributes` accepts `interfaces` and `device` only; any other entry (a stale `layer3_interfaces`, a typo) is a `ValueError` instead of a silent no-op success. The Catalyst Center and ACI mappers share `fact_common.py`.
- **`config-to-attributes` redundancy groups, Batfish format**: from `Interfaces.<name>.HSRP_Details` that `batfish-extract-facts` merges in from `hsrpProperties` (`doc/BATFISH_INTEGRATION.md`); same output shape, but no `name` (Batfish does not parse `standby <n> name`) and HSRP only for now (`vrrpProperties` exists but is not used yet).
- **`config-to-attributes` redundancy groups** (`source_format: genie`, "Add Interfaces"): `standby [G] ip|priority|preempt|name`
  and legacy `vrrp G ip|priority|preempt|description` lines become `interface_redundancy_groups[]` on the interface:
  `{name, protocol, protocol_group_id ("0"), virtual_ip: {address}, priority?, preempt, description?}`. `description` is
  the device's own text (the HSRP `standby <n> name`, or the VRRP description); `name` (that HSRP name, else
  `<interface>-<PROTOCOL>-<group>`) is for display only and is never written to Nautobot. The VIP gets `/len` when it
  lies in the interface's own subnet, else stays bare (the write step then only looks it up). A group without a VIP is
  dropped; authentication lines are never read; IPv6, timers and tracking are not. The IOS-XE `vrrp G address-family`
  form is not read either, and the step says so in its outcome summary (an interface that has it and no readable
  group). The same summary names Batfish interfaces that have HSRP group ids but no `HSRP_Details`.
  The step only builds the data; `update-nautobot-device` and `add-to-nautobot` write it (below).
- **`get-nautobot-attributes` redundancy groups** (HSRP/VRRP): the `interfaces` group also selects
  `interface_redundancy_groups { id name description protocol protocol_group_id virtual_ip { id address parent { namespace } } }`
  and the interface's `interface_redundancy_group_associations { priority interface_redundancy_group { id } }`
  (`nautobot.interfaces[].interface_redundancy_groups[]`, empty list when none; e.g. `...[0].virtual_ip.address`).
  The priority belongs to the association, so `attributes_from_detail` copies it onto the matching group and drops the
  association list: a bag read from Nautobot and written back keeps every priority. The group's `secrets_group` is not
  selected (nothing reads it, and its name would be stored in the run data). A plain field on every version, so it is
  in the static query, not a fragment.
- **`get-nautobot-attributes` cables** (group `cables`, separate from `interfaces`, which carries no cable data):
  the GraphQL selection depends on the Nautobot version (`GET /api/status/`, checked only when `cables` is
  selected): before 3.2 `cable { id type label tags status }` and `connected_endpoint`; from 3.2
  `cable { ... interfaces { device } }`. The option `normalize_cables` (default on) adds `cable.interfaces` (both
  ends) and `cable.far_end` on both versions and removes nothing. Through a patch panel the far end differs by
  version (path end before 3.2, only what the cable touches from 3.2). Code: `services/nautobot/devices/`
  (`attribute_bag.py`, `cable_normalize.py`, `version.py`).
- **`get-nautobot-attributes` sets `device.platform` and `device.network_driver` from Nautobot** when the
  device's platform has them, replacing values set earlier (for example by Get from List / Get from User);
  a missing Nautobot value keeps the existing one.
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

### One outcome API

A step that fails a device or builds its outcomes uses `workflow_steps/common/device_outcomes.py`, not a private copy:
`mark_device_failed(device, *, node_id, step_id, code, message, failure=None, **updates)` (builds the `DeviceError`;
error history kept, input never mutated), `fail_device_with_error(device, error, **updates)` (the same with an error
already built, for example by `device_error_from_exception`), `build_outcomes(context, succeeded, failed, *,
metadata=, success_summary=, failure_summary=)` (`success` always, `failure` only with failed devices),
`outcomes_from_buckets(context, buckets, *, metadata=)` (every handle, empty ones included, for the routers) and
`whole_step_failure(context, *, node_id, step_id, code, message, failure=, metadata=, empty_handles=)` (every device
fails with one error; a routing step lists its verdict handles in `empty_handles`). `abort_outcomes` and
`device_error_from_exception` stay in `partial_outcomes.py`. The older private `_fail*`, `_build_*outcomes` and
`_partition_*` functions in the step packages are legacy: `tests/unit/test_private_outcome_helpers_ratchet.py` pins them
per file, lets the number only fall and fails on a new one.

### Failure records of Batfish and pyATS (P-E, D3)

- **Batfish:** `BatfishError.failure` (`services/batfish/common/failure.py::classify_batfish_exception`) classifies from the
  exception class and the transport cause chain, never from text: `bad_request` (validation, a question that returned no
  table), `timeout` / `refused` / `dns` / `no_route` from the cause, otherwise `server_error`. A step that raises one is
  recorded with that kind instead of `internal_error`; the sentence stays withheld. A Batfish source that is missing or
  refused by the host policy is a `ValueError` (`batfish_context.resolve_batfish_connection`, the one resolver of
  `batfish-init-snapshot` and the query steps), so the author reads a configuration error.
- **pyATS:** a chunk-level shim failure keeps its `PyATSError.failure` (`timeout`, `auth_failed`, `server_error`, ...) in the
  per-device result (`run_batched`), and `get-pyats-running-config`, `get-pyats-snapshot`, `configure-replace-config` and
  `compare-pyats-snapshot` copy it onto the `DeviceError`. A device-level error from the shim (what the device printed)
  keeps its text capped at 300 characters with a generic `command_error`; an unexpected error is the class name plus
  `internal_error`. `batfish-extract-facts` stores the class name only when the HSRP question fails.

### Which exception text a failed device stores (P-E, D3)

`device_error_from_exception(exc, ..., keep_text=...)` is the one place that turns an exception into a stored message:
the text of a `ValueError` / `FileNotFoundError` (the step wrote it) is kept, anything else is reduced to the class
name plus a `FailureInfo`, so driver, SQL and secret text never reach the stored run. `keep_text` names the integration
errors whose text is sanitised at the source:

- **Nautobot** (`partial_outcomes.NAUTOBOT_TEXT`): every Nautobot read and write step passes it. The REST 400 text is
  cleaned and capped by the client, and it is the only place the operator reads why a write was refused
  (`name: this name is taken`).
- **ISE**: the client collapses whitespace and caps an ERS 400 at 300 characters, and sets `code="already_exists"` itself
  when a title says the object is already there (`ISEValidationError.code`). `add-to-ise` (the `exists` handle) and the
  group ensurer decide by that code, never by message text, so an address conflict worded the same way is a failure.
- **SSH driver, git and database** errors keep the class name and the `FailureInfo` only.

A step that writes `message=str(exc)` or `message=f"...{exc}..."` itself must have `exc` narrowed to a named class
that is not `Exception`, by its `except` clause or an `isinstance` check; a catch-all goes through
`device_error_from_exception`. `tests/unit/test_exception_text_sites_ratchet.py` (guard 9) enforces that and pins the
sites per file. `open-change-request` keeps the text of a `GitOperationError` (built by the app, scrubbed of URL
credentials) or a `ValueError` raised while staging; any other staging error keeps only its class name.

A failure that names a code names its cause too: `DeviceError(failure=...)`, a wrapper's `failure=` and the runner's
`Fail(code, message, failure)`. `workflow_steps/common/failure_records.py` holds the records most steps share
(`INVALID_INPUT`, `NOT_FOUND`, `MISSING_DATA`, `INVALID_RESPONSE`, `COMMAND_FAILED`); a cause with more facts (an HTTP
status, a transport kind) builds its own. `test_device_error_failure_ratchet.py` (direct `DeviceError(...)` calls) and
`test_failure_record_wrapper_ratchet.py` (calls through `_fail_device`, `mark_device_failed`, `Fail`, ...) may only fall.

### Empty branch and step-level failure (D2)

- **Validate first, then look at the devices.** A step parses and validates its config before it returns for an empty
  device list, so a config the step can never run with is reported on every run, not only on the one where devices
  arrive. `tests/unit/test_empty_branch_validates_config.py` pins this (an AST guard over every `execute`, and one
  unusable config per migrated step that must raise `ValueError` with no devices). Work that needs a session, a
  credential or a remote system (`require_session`, `resolve_ssh_credential`, `_bind_nautobot`) stays after the guard.
- **An empty branch is a no-op.** A step with `success` / `failure` handles returns `[success]` with the unchanged
  context (`open-change-request` too: nothing to review, nothing staged); a router (`route-on-attribute`,
  `route-on-content`, `list-contains`, `compare-data`, `login-successful`) answers every handle it declares, empty, with
  the context and its metadata unchanged.
- **A step-level failure marks the devices.** When the step as a whole fails (the AI is unavailable, the change request
  cannot be opened, the git operation fails) every device is FAILED with one `DeviceError` carrying the step's
  `FailureInfo` (`device_outcomes.whole_step_failure`), `success` is answered empty; `contact-the-ai`, `open-change-request`
  and the git steps do it. A step that loses a remote system part-way keeps the devices already done (`abort_outcomes`).

### Content writers

`filter-output`, `merge-content` and `update-content` read content a device already has, turn it into new text and
store it as `filtered_output` / `merged_content` / `updated_content`. `workflow_steps/common/content_step.py::run_content_step`
owns what they share: the per-device loop (`run_per_device`, so the failure contract of "One per-device runner"), the stored
artifact, the node-result entry `parsed[<node>][<kind>]` (`artifact_ref`, `step_node_id`, `output_key`, `size_bytes`, `kind`, plus
the step's own keys such as `match_counts`), the `PARSED` capability and the outcomes with `<node>.<prefix>_success_count` /
`_failure_count`. A step supplies a `transform(device_id, device) -> StoredContent` and, where it names one, a code for a
`ValueError` subclass (`nothing_to_merge`, `no_rule_matched`). `content_resolver` reads the entries back from one table
(`_NODE_RESULT_SOURCES`); `list_exportable_content` and `parse_content_source` take the asking step's id, so a message
names the step the operator configured.

### Import boundaries

`tests/unit/test_workflow_steps_import_boundaries.py` pins four rules: `common/` imports no step; no step
imports another step (shared code goes to `common/` or `services/`); a step imports a repository only at the
sites listed in that test (anything else goes behind a service); and only `services/execution/step_registry.py`,
`scripts/ai_inventory_filter.py` and `routers/workflow_crypto_attribute.py` import `workflow_steps`. A module
that exactly one step uses lives in that step's package.

Two repository imports went behind a service (W10-12): `start-workflow` reads and starts child runs through
`services/execution/child_runs.py` (each call opens a short session of its own and runs in a thread: the run's session
is shared with concurrent branches), and `contact-the-ai` resolves its service user with
`services/ai_assistant/workflow_user.py::resolve_workflow_user_id` (`WorkflowAiUserError.reason`: `not_set` or
`not_active`). A step turns its device and `network_driver_override` into a Netmiko device type with
`workflow_steps/common/device_type.py::connection_device_type` only (a test forbids a second call of the platform
resolver in a step).

### Author regexes on device or Nautobot data

A pattern an author writes and that runs on content the worker does not control (`route-on-content`
on a device config, `get-virtual-chassis` name filter and index regex on Nautobot names) never runs
in the worker process: `re` holds the GIL while it matches, so `(a+)+$` would stall every other step.
`workflow_steps/common/regex_search.py::search_many` sends the questions to the killable child
(`core/regex_isolated.py`, op `search_many`) in batches of at most 50 items / 4 MB; each pattern has
its own time limit. An unusable answer is `invalid` (bad pattern) or `stopped` (too slow, or the batch
failed): `route-on-content` fails that device (`invalid_regex` / `regex_stopped`), `get-virtual-chassis`
fails the step naming the setting.

Patterns that *remove* content use the second helper, `match_any(texts, patterns, ignore_case=)` (op `match_any`:
per text, whether any pattern is found; batches of at most 5000 texts / 4 MB): `filter-output` (key names of JSON, lines of
text) and the `custom_interface` strategy of `config-to-attributes` (`primary_ipv4_custom_pattern` on interface names,
case-insensitive). A stopped, failed or rejected batch raises `RegexStoppedError` (a `RuntimeError`): the device
(`filter-output`) or the step (`config-to-attributes`) fails, because "no match" must never be inferred from a failure
(it would keep the lines the author wanted removed). Patterns are still validated with `re.compile` at config parse time.

### Author templates and replace rules (S4-07)

Jinja templates and the `update-content` replace rules run whole, per device, in a killable child process too, never in
the worker: a template that loops for ages or a catastrophic pattern would otherwise hold a worker thread for good.

- **Jinja** (`render-jinja-template`, `update-config-context` template values, the `batfish-validate-facts` field
  template): `workflow_steps/common/jinja_render.py::render_jinja_template` is `async` and sends the template and its
  context as JSON to `core/jinja_worker.py`, which loads the sandbox `services/workflow_context/jinja_sandbox.py` (Jinja2
  and the standard library only) by path. A template problem comes back as plain data and is raised as the same
  `JinjaTemplateError` / `UnsafeTemplateValueError` with its `FailureInfo` (kind and line) as before. A context value
  that is not JSON fails the device ("not plain data"); JSON turns tuples into lists and dict keys into strings.
  Validation and `template_variables` only parse and stay in the worker.
- **Replace rules** (`update-content`): `workflow_steps/common/regex_search.py::replace_many` applies all rules of one
  device in one child (`core/regex_worker.py`, op `replace_many`).
- **Limits** (`core/isolated_process.py`): 10 s per device (`STEP_CHILD_SECONDS`, wall clock and the child's CPU
  limit), a rendered text of at most 8 MiB characters (`MAX_RENDERED_CHARS`), a config of at most 16 MiB characters
  before and after the rules (`MAX_CONTENT_CHARS`). At most four children per worker process (`STEP_CHILD_SLOTS`);
  a device waits for a slot and never fails "busy". The child runs with `python -I`, an empty environment and its own
  memory limit (where the platform allows it).
- **On a limit** the device fails, never falls back to an in-process run and never keeps its unchanged text:
  `TemplateStoppedError` (code `template_error` in `render-jinja-template`, `render_error` in `batfish-validate-facts`)
  or `ReplaceStoppedError` (code `regex_stopped` in `update-content`), both with `FailureKind` `resource_limit`
  (`failure_records.TEMPLATE_STOPPED` / `REGEX_STOPPED`). A bad replacement template (`\9`) stays a `ValueError` with
  its own text.

### The run's database session

A step gets its session with `workflow_steps.common.run_session.require_session(run, step_id)`; a run without one raises `RuntimeError("<step_id>: WorkflowRun has no active DB session")`. Nothing else in `workflow_steps/` may call `object_session` (`tests/unit/test_object_session_ratchet.py`); tests patch `workflow_steps.common.run_session.object_session` (`patch_object_session()`).

### Config push (W3a-02, -03, -04, -06, -13)

`run-command` (Run Command, config mode) and `deploy-rendered-template` (Deploy rendered Template) store a
`DeployResult` through one function, `workflow_steps/common/config_push.py::store_push_result` (transcript row, session-log
row of a failure, `copy running-config startup-config` row); each step passes its own command label and summary.

- **One marker list.** `services/network/netmiko/output_check.py` decides whether the device refused a line. `merge-config`
  (Merge Config) uses it too (`find_copy_error`): the shared refusal markers and a `%Warning` line follow `fail_on_cli_error`
  (default on, like the two push steps); an unreadable source file (`%Error opening`) always fails the device. The stored
  message is a closed label and the line number of the output, never the device text (a refused line may echo a secret).
- **One command output.** `upload-config` (Upload Config) fails a device whose source holds several items (a multi-command
  `run-command`) with `ambiguous_content`, as `compare-data` and `route-on-content` do (`content_resolver.single_item_or_message`).
- **TextFSM media type.** `CommandResult.structured_commands` lists the commands whose output came back as a TextFSM structure.
  `run-command` stores those as `application/json` and every other output (also the raw fallback when no template matched) as
  `text/plain`; the `parsed` entry of a raw fallback has `parsed: None` and an error, whatever the text looks like.
- **Run Command config mode on the runner.** `run-command` in config mode runs on `run_per_device` like exec mode's
  siblings do (no private gather and partition); the stored message of an exception is its class name plus the
  `FailureInfo`, never the driver text, and a failed result stores a fixed sentence (S4, W3a-10).
- **Render step hand-over (W3a-15).** `render_jinja_template` parses a template once per device (`from_string` raises the
  validator's syntax errors, same message, failure record and line); upstream command artifacts are read only when the template
  names `command`, `commands` or `commands_by_name` (`jinja_render.template_variables`); workflow validation warns
  (`duplicate_render_output_key`, tier 1) when a render step below another one on its path writes the same `output_key`.
- **One-token names.** `device_file_upload.parse_device_token` refuses a space or line break in `file_system`,
  `destination_filename` (`upload-config`, `upload-binary`, `configure-replace-config`) and `source_filename` (`merge-config`).

### `dry_run` in the Nautobot family, and the push steps

One meaning: **`dry_run` writes nothing and the preview is in the run result**, `device.dry_run_results[<node id>]`
(`step_flags.record_dry_run`; names and counts, never values that may be secrets). It reads Nautobot as it is now. Steps:
the three interface modes (`update-nautobot-ip`, `-vlan`, `-prefix`, refused without their mode), `remove-from-nautobot`
(`{would_remove_device, would_remove_ips, would_keep_shared}`; a device that is not found still fails; an address shared by two
devices of one run is reported as kept for both, the real run deletes it with the last holder), `update-config-context`
(`{mode, would_change, keys_before, keys_after, would_drop_keys, would_add_keys}`: top-level key names; mode `write` shows what the
replacement would drop), `update-nautobot-device` (`DeviceUpdateService.update_device(dry_run=True)`: `{would_update_fields,
interfaces: {would_create, would_update, would_delete}}`; `would_delete` only with `sync_interfaces`; it used to skip the step)
and `add-to-nautobot` (validates against Nautobot as before; a passing device stores `{validated, would_create_device,
would_create_interfaces}`). Workflow devices of `remove-from-nautobot` that resolve to the same Nautobot UUID are removed once
and share the outcome. A failed IP delete keeps the class of the Nautobot error (`permission_denied` for a 403, `already_exists`
for a 409, a retryable `server_error` for a 5xx).

The six device-push steps offer different safety features today (maintainer decision D10: not unified now):

| feature | `run-command` | `deploy-rendered-template` | `merge-config` | `upload-config` | `upload-binary` | `configure-replace-config` |
|---|---|---|---|---|---|---|
| `dry_run` | yes | yes | no | no | no | no |
| `retry_backoff_seconds` | yes | yes | yes | no | no | n/a (shim) |
| `read_timeout` | yes | yes | yes | no | yes | n/a (`job_timeout_seconds`) |
| `fail_on_cli_error` | yes | yes | always on (own list) | n/a | n/a | n/a |
| concurrency | pool threads | pool | pool | pool | pool | own semaphore (shim limit) |

### Controller kit and agent calls

The Cisco ACI and Catalyst Center steps share `workflow_steps/common/controller_sources.py`: `ControllerSource` names what
differs (device `source`, controller exception class and error code, validation error, the source-config service, the
"wrong source" code, an optional per-device check) and `ACI` / `CATALYST_CENTER` are the two instances. A step calls
`ACI.fact(fetch)` / `ACI.capture(fetch)` (a controller failure becomes an entry or a `FactError` with its `FailureInfo`; any
other exception propagates), `ACI.run_fact_step(...)` for a fact step, `CATALYST_CENTER.prepare_targets(context, run, ...)`
for a hand-written per-device loop (session, `split_targets`, one credential set per source before any I/O) and
`ACI.resolve_credentials(db, source_id, step_id=...)` for a single source. An ACI device without a pod and node id is
rejected with `aci_node_unknown` (`aci_node_of` reads it). The agent steps (`route-to-agent`, `get-from-agent`) share
`common/agent_call.py`: `parse_handler`, `parse_agent_source_id`, `parse_timeout` (1 to 600), `check_timeout` (a step timeout above
the agent's maximum is refused, never clamped) and `async with agent_client(connection)` (the client is closed on every exit).

### One per-device runner

A step that works on its devices one by one hands `workflow_steps/common/device_runner.py::run_per_device(context,
work, *, node_id, step_id, concurrency=None, only=None)` an async `work(device_id, device)` and gets a `Batch(ok, failed,
aborted)`. `work` returns the updated device, returns `Fail(code, message, failure=None)` for a failure it names itself,
or raises: an unexpected exception fails **that device only**, with `device_error_from_exception` (the text of a
`ValueError` / `FileNotFoundError` is kept, anything else is reduced to the class name plus a `FailureInfo`; driver, SQL
and secret text never reach the stored run). `concurrency` is `None` (all at once), `n` (semaphore) or `1` (in order);
only a sequential run may raise `AbortRun(message, failure)` (the remote system is lost): the run stops, the devices
already done stay in the batch and `batch.aborted` feeds `abort_outcomes`. `asyncio.CancelledError` always passes
through. Migrated: `secret-get`, `secret-set`, `secret-generate` (loop in `common/secret_manager_step.py`; a `ValueError`
from the service now fails that device with its text, it used to abort the step), `encrypt-attribute`, `decrypt-attribute`
(a `destination_path` that can never be written, such as a reserved bag, is probed once with
`attribute_write.probe_destination_path` and stays a step-wide config error; a write that fails on one device's data fails
that device), `store-in-db` and `get-from-db` (`concurrency=1`: one shared session, one device after the other) and
`configure-replace-config` (`concurrency` = the shim's own job limit; `Fail(device=...)` records the error on the device
that already carries its diff artifact refs), `deploy-rendered-template`, `merge-config`, `upload-config` and `upload-binary`
(artifact I/O and connection errors fail that device only; their error text is no longer stored, only the class name plus a
`FailureInfo`; `log_label=` writes the per-device "connecting / ok / failed" lines), and the device reads
`get-device-configs`, `read-config` (an empty file is refused with `empty_config`, a file above `MAX_CONFIG_BYTES` = 10 MiB
with `file_too_large` before it is read; every failure carries a `FailureInfo`), `login-successful` (`parsed.<node>.login.error` holds a closed code, never exception text; both outcome
handles are always answered, with `<node>.login_counts`), `reachable` (at most 50 pings in flight,
`MAX_CONCURRENT_PINGS`; library errors are recorded as `dns` / `no_route`, an unexpected error fails that device only) and
`get-device-location`. `discover-network` keeps its own breadth-first walk, but the walk is a per-device boundary too: a
visit that raises anything other than `VisitError` fails that seed (`unreachable`, class name in the `FailureInfo`) or
lists that neighbour as seen, it never loses the devices already visited, and a neighbour lookup that raises leaves the
neighbour as CDP reported it (`management_ip_lookup: unavailable`). The other steps still carry their own loops and move
family by family (P-C). W9 (files and git): `store-artifact` (sink, record and finalize errors: a `GitOperationError` keeps
its text, scrubbed of URL credentials, and its `FailureInfo`; any other exception is the class name plus a record; a git
prepare failure is a whole-step failure with the record on the outcome) and `read-from-file` run on `run_per_device`;
`get-age-of-backup` (two passes on `run_per_device`: the git lookups all at once while the repository lease is held, then the marker lookups one after the other on one database session; an unexpected error fails that device only and its traceback stays in the backend log), `open-change-request` (every failure outcome carries a `FailureInfo`, the message is scrubbed) and
the git steps (`git_workflow_step`) build their outcomes with `build_outcomes` / `whole_step_failure`. W6 (Nautobot jobs and
reads, ISE): `start-nautobot-job`, `check-nautobot-job` and `get-nautobot-attributes` run on `run_per_device`
(`keep_text=(NautobotError,)`: the Nautobot client sanitises its messages, so their text is stored; any other exception is
the class name plus a record, and a job already started is never lost because a later device raised); `start-nautobot-job`
keeps the request and response on a failed device through `Fail(device=...)`. `exists-in-nautobot` runs on `run_per_device` too (`keep_text=(NautobotError,)`, an unresolved `ip_address` is a `Fail("ip_unresolved")`, the three handles `exists` / `non_existing` / `failure` are built with `outcomes_from_buckets`); `split-virtual-chassis` and `get-virtual-chassis` have no per-device I/O and only use `mark_device_failed` / `build_outcomes`. `get-ise-tacacs-key` and `update-ise-tacacs-key` run on `run_per_device` with `concurrency=1` (shared inventory cache / one ISE session): a lost ISE connection raises `AbortRun` and feeds `abort_outcomes` as before; an unexpected exception now fails that device only (class name plus `FailureInfo`; `get-ise-tacacs-key` used to abort the whole step with the exception text). `add-to-ise` runs one device after the other
(`concurrency=1`), a lost ISE connection is `AbortRun` (the created devices keep `success`, `exists` keeps its handle), and
one bad value fails that device only (a non-ASCII digit in a prefix is `netmask_invalid`). `run_per_device` takes
`keep_text=` for such integrations; `device_error_from_exception` has the same parameter. W7 (pyATS and Batfish): `get-pyats-running-config`, `get-pyats-snapshot` and `compare-pyats-snapshot`
run on `run_per_device` (the compare step with `concurrency` = the shim's job limit and its match / mismatch verdict kept
per device; the get-steps over the devices that passed validation, `only=`). The batch call itself stays in
`common/pyats_batch.py` (chunks of devices per shim job are not part of the runner): a chunk whose answer is malformed or
raises fails that chunk only (the class name is the error), a sealed password that cannot be decrypted fails that device
(`credential_unreadable`), and the artifact store of `get-pyats-snapshot` is inside the per-device boundary.
`batfish-validate-facts` fails a device whose expected facts cannot be prepared (artifact read, template) instead of the step. W8 (controllers):
`get-catalyst-center-configs` runs on `run_per_device` (`concurrency` 5; a controller error keeps its text, an artifact
store error or any other exception fails that device only). `run-catalyst-center-command` keeps its request per chunk of
devices: a controller error and any other exception from the request fail that chunk's devices, a store or parser error
fails one device. `get-catalyst-center-client-data` and the shared fact driver (`common/fact_entries.collect_facts`,
the Catalyst Center and ACI fact steps) fail the one device whose query or `collect()` raised an unexpected exception; the
stored text of such an exception is the class name plus a `FailureInfo`. The per-controller `prepare()` of the driver is a boundary too: a `prepare` that raises fails the devices of that controller only (same record), the other controllers are collected as usual.

### Step config flags

Every boolean and whole-number step setting is read with `workflow_steps/common/step_flags.py`:
`parse_bool_flag(config, key, default=...)` and `parse_int_flag(config, key, default=..., minimum=..., maximum=...)`.
A required text setting is read with `require_text(config, key, step_id=..., default=...)` (stripped; blank raises `<step>: <key> is required`).
`"false"`, `"0"`, `"no"`, `"off"` and `""` are false, `"true"`, `"1"`, `"yes"`, `"on"` are true, `None` means the default,
and any other string (`"ture"`) fails the step with a configuration error naming the key. Do not write
`bool(config.get(...))`, `config.get(...) is True` or a private `_parse_bool`: `scripts/check_flag_parsing.py` (CI) fails
on them. Per-device errors built from an exception go through
`workflow_steps/common/partial_outcomes.py::device_error_from_exception`: it keeps the message of a `ValueError` /
`FileNotFoundError` (written by the step) and reduces anything else (a database or HTTP client error) to the class
name plus a `FailureInfo`, so driver text, SQL and parameters never reach the persisted step result.
`update-content` has `fail_if_no_match` (default off): a device where every rule matched zero times fails with
`no_rule_matched` instead of passing its unchanged content on.

### Placeholders in step text and `reveal_secrets`

`{path}` placeholders are found by one bracket-aware scanner (`workflow_steps/common/placeholder_scan.py`): a path may
hold list selectors, and a selector may itself hold a placeholder (`{nautobot.interfaces[name={custom.port}].description}`).
`update-attribute` expands every span it finds; the message steps (`render_placeholder_template`: `log-message`,
`notify`, `notify-on-error`, `get-from-db`, `route-on-content` ...) expand only spans that look like a path (outside
`[...]` only letters, digits, `_` and `.`), so `{hello world}` and JSON-like text stay as written.

`resolve_update_field_expression` has **no default** for `reveal_secrets`: a caller must say whether it may read a sealed
secret. Only the TACACS key of `add-to-ise` (Add to ISE) and `update-ise-tacacs-key` (Update ISE TACACS Key) passes `True`
(the key goes to ISE, the system that holds it). Every other site passes `False` and refuses the placeholder: `add-to-ise`
fails the device with `device_name_is_secret` / `ip_address_is_secret` / `description_is_secret`, `exists-in-nautobot` with
`ip_is_secret`.

### Resolver contract: one meaning per path

`device.<scalar>`, bare scalars, `{placeholders}` and Jinja read the same value
(`services/workflow_context/device_scalars.py`):

| Path | Value |
|---|---|
| `device.primary_ip4` | the bare address (`10.0.0.1`) in every resolver; the stored form is `device.primary_ip4_cidr` (`10.0.0.1/24`) |
| `device.id`, `.name`, `.hostname`, `.platform`, `.network_driver`, `.source`, `.source_id` | the stored scalar |
| `<bag>.<key>` | a leaf of an attribute bag; a bag with exactly one key also answers to its bare name `<bag>` (kept for existing workflows; a second key makes it `None`) |
| `parsed.<key>...` | `DeviceContext.parsed`; in filename/path templates `parsed` is the small `output_key` bag |

`undefined-and-unused` writes `parsed.<node_id>.<output_key>.undefined.parsed` / `.unused.parsed`. Like `batfish-extract-facts`, `get-pyats-running-config` and `get-pyats-snapshot` it nests under its own node id (W7-12), so two steps with the same `output_key` do not overwrite each other; `config-to-attributes` reads these two formats (`genie`, `batfish`) with `parsed_key` = `<node_id>.<output_key>`. The persisted copy of a
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

### Controller steps that add devices or write one result

`get-aci-devices` (Get from ACI), `get-catalyst-center-devices` (Get from Catalyst Center), `backup-aci-config` (Backup ACI
Config) and `compare-aci-subnets` (Compare ACI Subnets with Nautobot) have no incoming device to mark failed, so a controller
error (`AciAPIError`, `AciAuthError`, the Catalyst Center errors, `NautobotError`) ends the step on its `failure` handle:
`controller_failure_outcomes` returns the context unchanged, the summary `"<controller> request failed"` and the
`FailureInfo` the error carries (`phase="api"`, `kind="unknown"` when it carries none). The controller's text is not stored.
A rejected query or filter (`*ValidationError`) is a configuration error and raises.

### Notification caps and idempotence

`notify-on-error` posts at most `max_messages` (default 20) Mattermost messages per execution, then
one summary post; local notification rows are not capped. `notify` writes at most 100 rows plus a
final "... and N more devices" row. `notify-mattermost` cuts a post above 15 000 characters instead of
failing it. The run-level placeholders `{devices}` / `{device_count}` / `{run_summary}` of the notification steps are
substituted last, so a device named `{device.hostname}` is printed, not evaluated. `collect-statistics`
replaces its `(run, node, device)` rows on a re-execution, so a Hatchet retry does not double them.
`notify` and `notify-on-error` do the same: `notifications.node_id` (added by `AutoSchemaMigration`; NULL on
older rows) is the writing node, and `NotificationRepository.replace_for_node` replaces the rows of the
devices it writes (and the device-less "left out" row) for that `(run, node)` in one transaction, with a
rollback on failure. Mattermost posts cannot be taken back, so a retry of `notify-on-error` posts again.

**Failure policy of the notification steps** (D11): a configuration error raises and fails the step: a
missing or non-numeric value (`max_messages` is parsed by `parse_int_flag`: `true` and `7.9` raise), a
missing Mattermost source/team/channel (`parse_mattermost_target`), an unknown or invalid source. In
`notify-on-error` the source is resolved whenever Mattermost is enabled, not only when a device has an
error. A transport error never fails an error sink: `notify-on-error` logs it, counts it
(`mattermost_failed`) and stores its `FailureInfo` as `mattermost_failure` in the node's debug logs, and
the step still ends `success`. `notify-mattermost` and `send-mail` end on their `failure` outcome and carry
the `FailureInfo` of the client error (`MattermostAPIError.failure`, `MailSendError.failure`: status class,
timeout, auth, connect); an unclassified error gets `TRANSPORT_FAILED`.

### Names as keys

Steps that store something under the device **name** (`store-in-db`, `store-for-report`, `collect-client-data`, the secret
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
Status names are resolved by `MetadataResolver.resolve_status_id` for one content type
(`extras/statuses/?content_types=…`) and follow `next` too; a UUID is returned as it is, without checking
that it belongs to that content type. `GET /sources/nautobot/statuses` (allow-list `ipam.ipaddress`,
`ipam.prefix`) feeds the status pickers.

### Interface fields of `update-nautobot-device`

`device_identifier.mode` of `update-nautobot-device` and `update-config-context` is `from_context` (default) or `explicit`; any other text is a config error. When interface updates fail after the device fields were written, Update Device fails the device with `device_partially_updated` (the message says to run the step again).

Interfaces come from one of three sources (`interfaces_source`): `manual` rows, `nautobot_origin`
(every interface of the device's `nautobot` bag) or `parsed_list` (one interface per row of a
list on the device, e.g. TextFSM `show interfaces`: `parsed_list.source_path`, `field_map`
interface field -> column, `fixed_values` for the same value on every row). Every source supports
`mac_address`, `type`, `port_type`, `mode`, `speed`, `duplex`, `mtu` and `vrf`; values are
normalized by `workflow_steps/common/interface_values.py` (MAC -> `AA:BB:CC:DD:EE:FF`, speed ->
**Kbps** (`"1 Gbit"` -> 1000000; a bare number is Kbps), duplex -> `full|half|auto`, mtu -> int);
a value that cannot be understood is logged and left out. `vrf` is resolved by name through
`NetworkResolver.resolve_vrf_id` and must exist (an unknown VRF is a warning on that interface; the
other fields still apply).

- An **existing** interface is patched with only the fields given: `type` is not needed and
  `status` is only sent when given (a new interface still needs a `type` and defaults to
  `active`). A new interface without a type is reported as a warning and not created.
- An interface spec **without IP information** (no `ip_address`/`ip_addresses`) leaves the
  interface's existing IP assignments alone. With IP information the IPs are replaced as before.
- `parsed_list` fails a device whose list is missing or empty, and is refused together with
  `device_identifier.mode: explicit` and with `sync_interfaces` (sync deletes every Nautobot
  interface missing from the payload before any update runs, so an incomplete list would delete
  real interfaces; the dialog blocks both combinations too). A blank cell never erases a fixed
  value; a `description`/`type` cell that is not text (a list, an object, a sealed secret) is
  dropped and logged, never sent to Nautobot. The manual `interfaces` rows are only read and
  validated when `interfaces_source` is `manual`.
- **Device fields never copy a secret.** `build_resolved_update_data` resolves field and custom-field
  expressions with `reveal_secrets=False`; an expression that points to a sealed secret fails that
  device (as `update-nautobot-ip` does) instead of writing the cleartext to Nautobot.
- **`type_if_new`** (an interface-spec key, set by `parsed_list.new_interface_type`) is the type used
  only when the interface does not exist yet; `InterfaceRecordOps._create_or_update_interface`
  ignores it for an existing interface and never sends it to Nautobot, whereas `type` (also
  `parsed_list.fixed_values`) is always patched. `new_interface_type.mode`: `none` (default, a
  missing interface is skipped with a warning), `infer` (`infer_interface_type_from_name`) or
  `fixed` (+ `value`, lower-cased). An explicit `type` on the row wins over `type_if_new` on create.

**Redundancy groups (HSRP/VRRP)** — `redundancy_groups: {enabled, name_pattern, status}` on `update-nautobot-device` and `add-to-nautobot` (parsed by `workflow_steps/common/redundancy_groups_config.py`; `add-to-nautobot` writes them after the device and its interfaces exist, through `AddDeviceRequest.redundancy_name_pattern/_status`; default off;
`interfaces_source: nautobot_origin` only, refused otherwise). The groups come from
`nautobot.interfaces[].interface_redundancy_groups[]` (built by `config-to-attributes` from a Genie running
config or Batfish facts, or read by `get-nautobot-attributes`). `interfaces_from_nautobot_bag` cleans them:
protocol lower-cased and one of `hsrp|vrrp|glbp|carp`, group id as text; an entry without protocol, group id or VIP is
dropped. Per group it keeps:

- **`virtual_ip.address` as it is.** A bare address is *not* given `default_prefix_length`: a guessed length would be a
  different IP object (and could create a prefix) and would split peers that inferred different lengths.
- **`description`** (the device's own text); the entry's `name` is never written back as the description (from Nautobot it
  is the inventory name, `hsrp-1`).
- **`namespace`**: the VIP's own (`virtual_ip.parent.namespace.name` from Nautobot) or that of the interface address whose
  network contains it; unset means `Global`.
- **`priority`** only when the bag has one (a Nautobot read has it, copied from the association).

`InterfaceRedundancyOps` (`services/nautobot/devices/interface_workflow/redundancy_ops.py`, names in
`redundancy_naming.py`) runs after the interface and LAG steps and uses two REST endpoints (verified against
Nautobot 3.2.7):

- `dcim/interface-redundancy-groups/`: **name** and **status** are required (new group: `name_pattern`, `status`
  default `Active`), plus `protocol`, `protocol_group_id`, `virtual_ip` (an IP address *object*, never assigned to the
  interface) and `description`.
- `dcim/interface-redundancy-group-associations/`: **interface**, **group** and **priority** (required). A new association
  gets the bag's priority, else 100; an existing one is only PATCHed when the bag has a priority that differs, so a bag
  without priorities never resets stored ones.
- **The virtual IP** is created through `ensure_ip_address_exists` **inside the same lock as find-or-create** (devices run
  concurrently; two peers must not both create it), and an "already exists" answer (another worker) is followed by one more
  look-up. A bare address is only looked up by host in the namespace (`ipam/ip-addresses/?host=`); no match, or more than
  one, fails that group with a message saying to give it a prefix length.
- **Reuse before create:** a group is found by `protocol` + `protocol_group_id` + `virtual_ip`, so HSRP peers share one
  group and a re-run creates nothing. The lock is one per event loop. If Nautobot answers a create with a conflict (another
  worker), the group is looked up again and used when it is the same group; only when it is just the number that was taken
  is a new one computed (up to three times).
- **`name_pattern`** must contain `{next}` once (lowest free positive integer among the existing names that match the
  pattern, looked up with `name__isw=<text before {next}>`; gaps are filled) and may use `{protocol}` (`hsrp`).
  Default `hsrp-{next}`; at most 249 characters (the dialog checks this too).
- A group or association that fails marks the interface failed (the device leaves through `failure`, reason in the
  warnings). Nothing is deleted, also not with `sync_interfaces` (which, with a bag from `config-to-attributes`, deletes
  every interface the parser did not emit: do not combine them). Not covered: IPv6 groups, removing a group when the
  config no longer has it, and a group list longer than about 50,000 names (1000 per page, at most 50 pages) for the counter.

### IP address steps: `get-next-free-ip`, `add-ip-to-nautobot` and `update-nautobot-ip`

All are in the `nautobot` palette category; the first two share
`workflow_steps/common/nautobot_prefix_lookup.py` (`find_containing_prefix`, `LookupFailure`).

- **Prefix and namespace.** `get-next-free-ip` finds the prefix by namespace (name, UUID or `{path}`,
  default `Global`) and CIDR, then reads `/ipam/prefixes/{id}/available-ips/`. A value with a length
  (`192.168.178.240/24`) is reduced to its network (`192.168.178.0/24`). A bare address
  (`{device.primary_ip4}`) has no length: the step asks Nautobot for the most specific prefix of the
  namespace that contains it (`contains=`). Several spellings of one prefix (`Global` and its UUID, an
  upper- and a lower-case IPv6 address) share one free list, so one execution never hands an address out twice.
  `start_offset` is counted from the network address; at most 1000 free addresses are read per request, and a
  shortage after that is reported as `free_ip_window_exceeded`, not as an exhausted prefix.
- **Ask the Net has the same lookup as a tool**, `get_next_free_ip` (`libs/nautobot_read/nautobot_read/queries/free_ip.py`,
  `doc/AI_TOOL_CHAIN.md` §31). It does not import this step (external code must not import `workflow_steps`), so the
  rules are written twice: the CIDR reduction of host bits, a bare address meaning its most specific containing prefix,
  `start_offset` counted from the network address, the 1000-address read window and the `free_ip_window_exceeded`
  distinction. **A change to those rules here needs the same change there, and the other way round.** The tool
  differs on purpose: no default namespace (several namespaces is a question), `count` at most 20, and a shortage is
  an answer, not an error.
- **Nothing is reserved.** `get-next-free-ip` only reads. Parallel runs and fan-out children can receive the
  same address until it exists in Nautobot (see the concurrency table).
- **`add-ip-to-nautobot` writes through the shared facade** (`DeviceCommonService` → `IPManager`,
  `PrefixManager`): no step-specific REST code creates IPs or prefixes. An address without a length takes the
  length of its containing prefix; if none exists, `create_prefix` creates the parent prefix (status Active)
  with `default_mask_length` (empty: 24 / 64). That value is only read when `create_prefix` is on and must fit
  the address family.
- **An existing address is reused, not changed.** Its status, description, DNS name and prefix length are left
  alone (`use_assigned_ip_if_exists`). With `interface_name` the address is attached only if it is not
  assigned to another interface (`ip_assigned_elsewhere`); `set_primary` is IPv4 only.
- **Order of work.** Everything that can be checked without writing (address, namespace, status, device,
  interface) runs before the address is created; `result_attribute` (a bag path, never `device.*`) is
  written only when the device succeeds. A failure after the write names the IP address ID in the message.
- **`add-ip-to-nautobot` never copies secrets.** It resolves `{path}` values with
  `reveal_secrets=False` (`resolve_update_field_expression(..., reveal_secrets=False)` in `common/value_expression.py`) because they are written
  to Nautobot or into an error; a sealed secret fails the device (`<field>_is_secret`). A `description` or
  `dns_name` expression that resolves to nothing fails the device, and its error messages do not repeat the
  resolved address. `get-next-free-ip` resolves its prefix and namespace values the same way (it only reads,
  but the values go into Nautobot queries and error text): a sealed secret fails the device
  (`prefix_is_secret` / `namespace_is_secret`). It looks the namespace up through the shared service, so two
  namespaces of one name fail the device (`namespace_ambiguous`). `add-ip-to-nautobot` records
  `ip_assigned_elsewhere` as `already_exists` and `primary_ip_failed` as `bad_request`; its "enable
  `create_prefix`" hint comes from the typed `NoParentPrefixError`, not from message text.

- **`update-nautobot-ip` ("Update IP") changes an existing address.** It is identified by its Nautobot
  UUID (`ip_id`, a fixed value or a `{path}`, typically the `result_attribute` of Add IP to Nautobot); an
  address or any other non-UUID text fails the device with `ip_id_invalid`. It can set `namespace`, `type`
  (`host` / `dhcp` / `slaac`, else `type_invalid`), `role` (name or UUID of a role for IP addresses, else
  `role_not_found`), `status`, `dns_name` and `description`. **Only filled-in fields are sent; an empty field
  is left alone and a value cannot be cleared** (a step with no field at all is a configuration `ValueError`;
  every field resolving to empty text fails the device with `nothing_to_update`). The write goes through the
  shared facade (`DeviceCommonService.update_ip_address` → `IPManager.update_ip_address`): it reads the
  address, and sends a PATCH with only the values that differ. An address that already has every value is a
  `success` and counted as `unchanged` in `metadata["<node>.update_ip_counts"]`; a missing address fails the
  device with `ip_not_found`. Namespace, status and role names are looked up once per distinct value.
  Like Add IP, it resolves `{path}` values with `reveal_secrets=False` (`<field>_is_secret`) and never repeats
  a resolved value in an error, so a failed namespace, role or status lookup reports a fixed sentence, not the
  name. It produces no attributes (`produces: []`).
  **Namespace is a move of the parent prefix.** Nautobot answers 200 and changes nothing when `namespace` is
  PATCHed on an existing address, so the step never sends it: it finds the most specific prefix of the target
  namespace that contains the host address (`find_containing_prefix`) and PATCHes `parent`. A namespace with no
  such prefix fails the device with `prefix_not_found` and writes nothing; an address already under that prefix
  is `unchanged`. Verified on Nautobot 3.2.7 (live: moved, repeat no-op, empty namespace refused); a version that
  makes `parent` read-only fails the device with Nautobot's error. A DNS name is compared case-insensitively
  because Nautobot stores it in lower case, and the manager rejects an `ip_id` that is not a UUID.
  *Concurrency:* each device PATCHes the address it names, so fan-out children and sibling branches are safe
  as long as they name different addresses; two devices resolving to one `ip_id` with different values make
  the last write win.
  **IP addresses from interfaces** (`ips_from_interfaces: true`, `ip_version`, `dry_run`;
  `workflow_steps/update_nautobot_ip/interfaces_mode.py`). Unlike the VLAN and prefix modes the **values are not derived
  from the device**: the user configures `status` / `type` / `role` / `namespace` / `dns_name` / `description` once and the
  step applies them to **every IP address on the device's interfaces** (`nautobot.interfaces[].ip_addresses[]` of the
  attribute bag; Get Nautobot Attributes with interfaces on). `ip_id` must be empty (the step refuses it) and at least one
  value is still required. `ip_version` (`4` / `6`, empty = both) filters the addresses. An address listed on several
  interfaces is handled once. Every address costs one GET (and a PATCH when it differs); concurrency 5.
  - **Shared addresses are skipped.** An address that is also assigned to another device's interface or to a VM interface
    (HSRP / VRRP virtual IP, anycast), or whose assignments cannot be confirmed, is not touched (`IPManager.shared_ip_ids`,
    one `ipam/ip-address-to-interface/?ip_address=` read per address, the same rule as `list_device_ip_ids`). It is counted
    in `skipped_shared` and listed in the dry-run preview. This is also why an address handled here belongs to one device only.
    **Limit:** only these assignment rows are looked at. An address that is exclusive there but also used as a NAT or service
    address elsewhere is still updated (the same limit as Remove from Nautobot). Interface ids from the bag and from Nautobot
    are compared without regard to case.
  - **Per-address values.** `dns_name` and `description` may use `{ip.address}`, `{ip.host}`, `{interface.name}` (the first
    interface that lists the address) and `{interface.slug}` (a DNS label: `Gi0/0.100` -> `gi0-0-100`), besides device
    `{path}` expressions (`address_values.py`). A token value never carries braces, an unresolved placeholder or one that
    points to a secret fails the device (`dns_name_unresolved` / `..._is_secret`) before anything is written, never empty text.
    A value that *renders* empty for one address (`{interface.slug}` of an interface named `///`) skips only that address:
    it is counted in `skipped_empty` and listed in the dry-run preview, and the rest of the device is updated. The
    `nothing_to_update` code stays for a configuration whose device-level fields all resolve to nothing.
  - **Outcome.** A device with any failed address leaves through `failure` ("n of m addresses could not be updated", the
    first error's code); the other addresses were still written (one PATCH per address, so none is half-updated). A device
    without `interfaces` in its attributes fails with `interfaces_missing`. Counts in `metadata["<node>.update_ip_counts"]`:
    `updated`, `unchanged`, `failed`, `skipped_shared`, `skipped_empty`, `dry_run`, per address.
  - **`dry_run`** writes nothing: `IPManager.plan_ip_update` reads each address and the device gets
    `dry_run_results[<node>] = {would_change: [{ip_id, address, fields}], unchanged, skipped_shared: [...], skipped_empty: [...]}`
    (names of the fields, not their values; a namespace move shows as `namespace`). **`dry_run` without
    `ips_from_interfaces` is a configuration error**, not ignored: a manual run would otherwise write.
  - Loopback, management and the primary IP are included like any other address; there is no interface filter yet.

### VLAN step: `update-nautobot-vlan`

`update-nautobot-vlan` ("Update VLAN", `nautobot` palette category, IPAM sub-group) changes an existing
VLAN. Outcomes `success` / `failure`, `requires: [identity]`, `produces: []`. Structure and conventions follow
`update-nautobot-ip`; the write goes through the shared facade (`DeviceCommonService` → `VLANManager.update_vlan`).

- **Selecting the VLAN.** `vlan_id` (UUID, fixed or `{path}`) wins when set; otherwise `vid` (1-4094) is looked up
  with `ipam/vlans/?vid=` and narrowed by the optional `vlan_group` (name or UUID). A VID is not unique in Nautobot:
  no match fails the device with `vlan_not_found`, several with `ambiguous_match` (nothing is written). A value that
  is not a UUID / not 1-4094 fails with `vlan_id_invalid` / `vid_invalid`; the value is never echoed.
- **Fields.** `name`, `description`, `status` (names looked up for content type `ipam.vlan`; `GET
  /sources/nautobot/statuses` allows it), `role` (name or UUID, content type `ipam.vlan`) and `locations`.
  **Only filled-in fields are sent; an empty field is left alone and a value cannot be cleared.** A step with no
  field and no location is a configuration `ValueError`; every field resolving to empty fails the device with
  `nothing_to_update`.
- **Locations.** A VLAN can belong to several locations (a client VLAN valid in every site). `locations` is a
  comma / newline separated list (parsed like CSV, so a name with a comma is quoted: `"Frankfurt, West"`); every entry is
  a fixed name, a UUID or a `{path}` expression (an expression that resolves to a list is split the same way). `locations_mode`
  (default `replace`) decides how it meets the VLAN's current locations: `replace` = exactly this list, `add` =
  current plus these, `remove` = current minus these (the only way to drop a location). The sets are compared as sets,
  so a list that already matches is `unchanged` and nothing is PATCHed. An empty list leaves the locations alone.
  Location, VLAN group, role and status names are looked up once per distinct value, location and group names
  case-insensitively (`name__ic`, then compared locally; an exact-case match wins, a partial match never counts) and a UUID
  is checked to exist (a status or role UUID is lowercased, so an uppercase one is not re-sent on every run); an unknown one fails the
  device (`location_not_found`, `vlan_group_not_found`, `role_not_found`, `status_not_found`) with a fixed message,
  several matches with `ambiguous_match` (use the UUID).
- **Secrets.** `{path}` values are resolved with `reveal_secrets=False` (`<field>_is_secret`); resolved values are
  never repeated in an error.
- **Counts** are in `metadata["<node>.update_vlan_counts"]`: `updated`, `unchanged`, `failed`.
- **VLANs from interfaces** (`vlans_from_interfaces: true`, `workflow_steps/update_nautobot_vlan/interfaces_mode.py`). Instead
  of one selected VLAN the step reads each device's `nautobot` attribute bag (Get Nautobot Attributes with interfaces on):
  `location.id` and the `untagged_vlan` / `tagged_vlans` ids of every interface, and adds the device's location to each VLAN
  (`add` only, nothing is removed). `vlan_id`, `vid`, `vlan_group`, the fields and `locations` must be empty (the step
  refuses them; the panel clears them when the mode is switched on). A device without a location or without `interfaces` in its
  bag fails with `device_location_missing` / `interfaces_missing`. **Nautobot, not the bag, decides whether a VLAN already has
  the location** (the bag is a snapshot: a location removed after the attributes were read must still be found missing, in a
  dry run too): every VLAN is asked, `update_vlan` reads the assignments and POSTs only a missing one. Each (VLAN, location)
  pair is handled once per execution however many devices and interfaces use it, so devices at one site do not race to create
  the same assignment, and the counts are per pair (`updated` / `unchanged` / `failed` plus `dry_run`). **`dry_run: true`**
  writes nothing: `VLANManager.missing_locations` reads the VLAN's assignments and each device
  gets `dry_run_results[<node>] = {would_add_location: [{vlan_id, vid, name}], already_assigned, location_id}`. `dry_run`
  without `vlans_from_interfaces` is a configuration error (not ignored). Parallel
  runs (other workflows) on the same pair can still collide; the second POST then fails that device and a re-run completes it.

- **Concurrency.** Each device PATCHes the VLAN it selects, so fan-out children and sibling branches are safe as long
  as they select different VLANs. Two devices on one VLAN with different values: the last write wins; `add` /
  `remove` read the current locations first and are not atomic, so parallel runs on one VLAN can overwrite each other.
- **`locations` is not a VLAN field in the REST API.** It is read-only on `ipam/vlans/`: a PATCH of it answers 200 and
  changes nothing (and the field is left out of a GET unless `exclude_m2m=false` is sent). The locations are the rows of
  `ipam/vlan-location-assignments/` (`vlan`, `location`), so `VLANManager.update_vlan` reads the VLAN's assignments
  (`?vlan=`), then POSTs the missing ones and DELETEs the surplus ones. The other fields are one PATCH of the differing
  values. Fields are written before the locations and Nautobot has no transaction, so a failure after something was
  stored leaves the device through `failure` with code `vlan_partially_updated` (the message names what is already
  written); running the step again completes it. A failure before any write is the plain error.
  The interface attribute query (`attribute_bag.py`) reads a VLAN's `locations` (list), never the legacy `location`,
  which raises in Nautobot for a VLAN with more than one location. Verified live on Nautobot 3.x (replace / add / remove, idempotent re-run, unknown location,
  unknown VID).


### Prefix step: `update-nautobot-prefix`

`update-nautobot-prefix` ("Update IP Prefix", `nautobot` palette category, IPAM sub-group) is the VLAN step for IP prefixes
and works the same way (outcomes `success` / `failure`, `requires: [identity]`, `produces: []`; the write goes through
`DeviceCommonService` → `PrefixManager.update_prefix`). Read "VLAN step" above for the shared rules; the differences:

- **Selecting the prefix.** `prefix_id` (UUID, fixed or `{path}`) wins; otherwise `prefix` (a network such as `10.0.0.0/24`,
  checked with `ipaddress`, `prefix_invalid` when it is not one) is looked up with `ipam/prefixes/?prefix=&namespace=` in
  its **canonical form** (`2001:DB8::/32` is searched as `2001:db8::/32`, the text Nautobot stores), and a returned row whose
  `prefix` is another network is dropped (`PrefixManager.find_prefixes`), narrowed by the optional `namespace` (name or UUID). The same network can exist in several namespaces: no match fails the
  device with `prefix_not_found`, several with `ambiguous_match`.
- **Fields.** `description`, `status` and `role` (names looked up for content type `ipam.prefix`) and `locations` with
  `locations_mode` (`replace` / `add` / `remove`). There is no `name`. Errors: `prefix_partially_updated`,
  `namespace_not_found`, `location_not_found`, `status_not_found`, `role_not_found`.
- **Locations** are `ipam/prefix-location-assignments/` rows (`prefix`, `location`), the same mechanism as the VLAN's. The code
  is shared: `services/nautobot/managers/location_assignments.py` (read, add, replace, remove, `PartialUpdateError`; the VLAN
  manager raises the same class). The assignment row ids Nautobot returns are checked as UUIDs
  **before** the first write (they go into a DELETE path) and so are the location ids sent in a POST; every row of a location
  that goes is deleted.
- **Prefixes from interfaces** (`prefixes_from_interfaces: true`, `dry_run`): as for VLANs, but the objects are the **parent
  prefix of every IP address** on the device's interfaces (`nautobot.interfaces[].ip_addresses[].parent`: `id`, `prefix`,
  `locations`, `namespace`). Get Nautobot Attributes now selects `parent { id prefix locations { id name } namespace { id name } }`
  for interface addresses (`services/nautobot/devices/attribute_bag.py`); **a bag read before that has no parent data and the
  mode finds nothing for it**, so read the attributes again. Counts are in `update_prefix_counts`; the preview entries are
  `{prefix_id, prefix, namespace}`. `dry_run` applies to this mode only; without `prefixes_from_interfaces` it is a configuration
  error. As for VLANs, Nautobot (not the bag's `locations`) decides whether a prefix already has the location.
- **Shared engine.** Both "from interfaces" modes run `workflow_steps/common/device_location_sync.py` (`LocationSyncSpec`:
  how to find the objects in the bag, how to write one, how to check one); each step's `interfaces_mode.py` only supplies those.

### Removing a device: `remove-from-nautobot`

`remove-from-nautobot` ("Remove from Nautobot", `nautobot` palette category, DCIM sub-group) deletes a device
from Nautobot. Outcomes `success` / `failure`, `requires: [identity]`, `produces: []`.

- **Only a UUID selects the device.** `device_id` is a fixed UUID or a `{path}` expression (default
  `{device.id}`), resolved with `reveal_secrets=False`. A value that is not a UUID fails the device with
  `device_id_invalid` (`device_id_unresolved`, `device_id_is_secret` for the other refusals); the value is never
  echoed. An unknown UUID fails it with `device_not_found` and nothing is deleted.
- **`remove_ip_addresses` (default off).** Per device: the addresses assigned to its interfaces are looked up
  (`IPManager.list_device_ip_ids`), those only this device holds are deleted (`delete_ip_address`), then the device
  (`DeviceManager.delete_device`), all through the `DeviceCommonService` facade. An address that is also assigned
  to an interface of another device or to a VM is **kept** and counted as `ips_shared_skipped`; so is one whose
  lookup does not confirm this device as the only holder (an empty answer never leads to a delete). Other holders
  (NAT inside/outside, services, FHRP groups) are not checked.
- **One device at a time with address removal.** Holders are read from Nautobot's current state, so with
  `remove_ip_addresses` on the devices of one run are processed sequentially: the last holder of an address
  shared by devices of the same run sees it as exclusive and deletes it. Without the flag they run in parallel.
- **No atomic delete.** Nautobot cannot delete a device and its addresses together. If the device delete fails
  after addresses were removed, the device leaves through `failure` with `device_delete_failed`, and the message
  lists the deleted address ids; nothing is rolled back and the operator checks Nautobot. If an address delete
  fails the device is not removed (`ip_delete_failed`); an address that is already gone (a retry) is skipped, so
  running the step again continues where it stopped. A device that disappears between check and delete is
  `device_not_found`.
- **Counts** are in `metadata["<node>.remove_counts"]`: `devices_removed`, `ips_removed`, `ips_shared_skipped`,
  `failed`.

### Creating devices from a file: `get-git-devices` → `set-default-attributes` → `add-to-nautobot`

- **Mapping targets** (`get-git-devices`): besides the Nautobot attributes, a column can feed the IP
  namespaces `primary_ip4.parent.namespace.name` and `interfaces.ip_addresses.parent.namespace.name`
  (each needs its address column mapped, or validation fails) and `custom.<name>`, a value that is not
  Nautobot data. Custom values live in `attribute_bags["custom"]`, never in the `nautobot` bag; they resolve
  as `{custom.<name>}` in file-path templates (strict mode fails on an empty one, like `nautobot.` and
  `git.`) and as `{{ custom.<name> }}` in Jinja. The full list is in `doc/MANUS_BASIS_DATATYPE.md`.
- **Primary IP per device** (`get-git-devices`, target `_is_primary`): a true/false column (multi-line CSV, one
  line per interface) picks the interface whose IP, with its namespace, becomes the device's `primary_ip4`. It
  needs an `interfaces.ip_addresses.address` column and cannot be combined with any `primary_ip4.*` target.
  No flagged line: no primary IP. The step has a `failure` outcome: a device with more than one flagged
  interface (`multiple_primary_ip`; the same address in two namespaces counts twice), a flagged line without an
  IP (`primary_without_address`) or a non-boolean flag (`invalid_primary_flag`) goes there with status `failed`
  and gets no `primary_ip4`; all other devices continue on `success`. **With fan-out enabled there is no
  `failure` outcome** (the engine fans out from `success` only): such a device fails the whole step. The preview
  lists only accepted devices (`rejected_count`). Messages never quote the flag cell. "Load keys from repository"
  pre-fills `interface_address`, `is_primary` and `namespace` columns. Full rules in
  `doc/MANUS_BASIS_DATATYPE.md`.
- **Default interface type** (`set-default-attributes`, `interface_type`): sets `type` on every interface of the
  `nautobot` bag that has none and changes nothing else on it (with `overwrite` it also replaces an existing
  type). It creates no interfaces and is not stored in the bag (`common/attribute_defaults.py`).
- **IP namespace** (`add-to-nautobot`, interfaces from the Nautobot attributes): the namespace of an interface IP
  is its `parent.namespace.name`, else a `namespace` (name or `{name}` object), else `Global`; a blank value
  counts as unset (`interface_workflow/payload.py::ip_namespace`).
- **Pre-flight checks** (`services/nautobot/devices/creation_preflight.py`): before the device is POSTed, the step
  checks read-only that every named interface has a `type`, every IP parses, every namespace exists and,
  with `add_prefix` off, every new IP has a parent prefix (queried by the *host* address with
  `ipam/prefixes/?contains=`: Nautobot picks the parent by containment of the host, the mask plays no part,
  verified on Nautobot 3.2.7). With `add_prefix` on, prefixes are created when the IP is added. A failed
  check creates nothing and fails the device with `preflight_failed`; `dry_run` reports the same problems.
  A lookup that itself fails is logged and skipped. Whether the name is taken is deliberately not checked
  beforehand, so the POST's own 400 keeps selecting `device_already_exists`.
- **Error codes** (`add-to-nautobot`, route on `error.code`): `device_already_exists` (the 400 is about the
  device name: field `__all__`, `non_field_errors` or `name`; a duplicate `asset_tag` or any other field is a
  plain failure), `preflight_failed` (nothing created), `device_created_incomplete` (device created, some
  interfaces or IPs failed; the Nautobot id stays on the failed device so a repair or removal step can find
  it; this includes a missing parent prefix with `add_prefix` off).
- **Nautobot's reason in the message.** Response text stays out of exception messages (they are saved on the
  device and in run results) with one exception: a REST **400** whose body is structured validation JSON gets
  its cleaned text appended (`services/nautobot/common/response_detail.py`: markup and control characters
  removed, at most 5 entries, 300 characters). The failing top-level fields are kept as
  `NautobotError.fields`. 5xx, HTML, non-JSON and GraphQL errors keep the payload-free message, and
  `FailureInfo` never copies message text.

### Calling an agent: `route-to-agent`

`route-to-agent` (palette category *Routing*) sends selected attributes and content, per device, to a handler
on an external agent and writes the declared keys of the JSON answer under `destination_path` (for example
`agent.geo.location`). Full design, security model, protocol and operations: `doc/AGENT_INTEGRATION.md`. The
rules a step author must keep:

- **Enrichment only.** `requires: [identity]`, `produces: [attributes]`, outcomes `success` / `failure`. The
  agent never chooses an outcome. The step always emits `success` (possibly empty) and `failure` when a
  device failed.
- **Secrets never leave.** `input_paths` are checked when the step starts (`secret_path_problem` in
  `route_to_agent/request.py`): known secret paths, the config-context subtrees, any **parent** that would
  carry them along (the bag root `nautobot`) and any path segment that names a secret are a `ValueError`.
  Values are checked per device: a sealed secret fails the device with `source_sealed`, a non-empty value under
  a secret-looking key with `source_secret`. A step that sends device data to an external process must apply
  the same rules (`SECRET_BAG_PATHS`, `SECRET_BAG_SUBTREES`, `is_secret_key_name`).
- **The destination is a bag, never the device.** `destination_path` may not start with `device`, a device
  field name, `parsed`, `run_input` or `error`; it is probe-written through `set_device_attribute` at parse
  time and written as real nested dicts (never a flat dotted key).
- **Output is an allow-list.** Only `output_keys` are accepted; each value must be JSON within
  `STEP_OUTPUT_VALUE_MAX_BYTES`, nested at most 8 levels (measured iteratively, so absurd nesting cannot
  exhaust the recursion limit). A violation is `output_rejected` and never echoes the values.
- **One call per device, bounded.** Calls run concurrently up to the agent source's `max_concurrency`. A step
  `timeout_seconds` above the source's maximum is a configuration error, not silently capped.
- **Systemic failures stop early.** `AgentOfflineError` / `AgentAuthError` fail the devices not yet sent with
  the same cause. A late (expired) answer is only a timeout for its device: it says nothing about the secret.
- Failure codes and kinds: `doc/AGENT_INTEGRATION.md` "Failures and what they mean".

### Getting devices from an agent: `get-from-agent`

`get-from-agent` (artifact type `inventory_selector`, `requires: []`, `produces: [identity]`, outcome `success`
only) is the inventory counterpart of `route-to-agent`: it calls **one** handler on an agent and builds the
workflow's devices from the answer. Protocol, secrets and operations: `doc/AGENT_INTEGRATION.md`. The rules:

- **Request.** `attributes` is a list of `{name, value}` rows sent as `inputs.attributes` (`params` is `{}` and
  `inputs.content` is empty). A value is fixed text or a whole-value `{run_input.<name>}` reference resolved from
  `run.run_inputs` when the step runs (`get_from_agent/request.py`). There is no device yet, so no attribute paths.
- **Secrets never leave.** A secret-looking attribute name (`is_secret_key_name`), a missing run input, a sealed
  (secret-type) run input or a non-scalar run input is a `ValueError`.
- **Answer.** `{"devices": [{name, ip_address, network_driver}, ...]}`, the rows of `get-from-list`, checked by
  `normalize_device_entries(..., step="get-from-agent")` (IP syntax, canonical driver, de-duplication). No other
  key is accepted; at most 5000 rows.
- **No partial inventory.** An agent error (offline, auth, timeout, handler error), a malformed answer, **one**
  invalid row (including a blank one with neither name nor IP) or an empty list fails the step
  (`RuntimeError`/`ValueError`). The step never skips rows; only exact duplicates (same name, IP and driver) are merged.
- **Host policy.** The agent chooses where the workflow's SSH credential goes, so every name and IP gets
  `core.safe_hosts.validate_device_host` (no loopback, link-local, unspecified or multicast literal, no metadata name)
  and an `ip_address` must be a plain address (no CIDR suffix, no leading zeros).
- **Run input references** must be the whole value; a value that contains `{run_input.` but is not a whole,
  well-formed reference fails the step instead of being sent as text.
- `{node_id}.devices` lists at most 500 names (the persisted copy of a larger value would be replaced by a marker);
  `{node_id}.total` is always exact.
- **Devices.** `device_context_from_entry(..., source="agent", attribute_bag_name="get_from_agent")`; metadata
  `{node_id}.total`, `.devices`, `.agent`; fan-out block identical to the other inventory steps.
- `timeout_seconds` above the agent source's maximum is a configuration error (as in `route-to-agent`).
- Example handlers: `list_devices` in `agent/example-agent/handlers/examples.py` (a fixed list) and the real inventory
  agent `agent/reachable-ip-inventory/` (attribute `tag`: the reachable hosts of the Nautobot prefixes with that tag).

### Enriching devices from a CSV file: `enrich-attributes`

The sibling of `read-from-file` for lookup tables. The file (export directory or `git_repository_id`, same root
resolution and containment as `read-from-file`; the git read does **not** pull unless `refresh_repository` is on) is a CSV with a header row; one column
(`key_column`) identifies the device. Example, `serial;data` / `131184641;example data`.

- **Matching.** The device value is `device_attribute_path` (any scalar attribute, e.g. `nautobot.serial`), compared
  with each row's key: `match_mode` `match` (equal) or `contains` (device value contains the key; an empty key never
  matches), optionally `case_insensitive`. The **first** matching row in file order wins (`contains` stops at the
  first hit, so a short key earlier in the file beats a longer one; order the file accordingly). Duplicate keys in
  `match` mode log one warning for the file. A device with no matching row, or whose path has no scalar value, or
  holds a sealed secret (never decrypted for the comparison), continues unchanged on `success`.
- **Result.** Every column except the key column is deep-merged into the device bag at `destination_path`
  (`merge_into_device_attribute`, `overwrite` as in `read-from-file`): `inventory.data = "example data"`. Empty cells
  are skipped (an `""` key would block a real value when `overwrite` is off). A blank `destination_path` means `data`.
  A column that would land on, or inside, a **sealed secret** is never merged, whatever `overwrite` says: that device
  takes the `failure` outcome (`sealed_secret_conflict`).
- **Parsing.** `csv` module, `delimiter` (default `;`, one character or `tab`), UTF-8 with an optional BOM, all values
  trimmed strings, blank lines skipped. The file is read once per run (at most 10 MiB and 200 000 rows). A missing file,
  a missing `key_column` header, a duplicate header or an empty file fails the **step**; a symlink is refused like a
  missing file, and `git_repository_id` must be a whole number. Only a sealed-secret conflict or a merge error fails
  one device (`failure` outcome, each with a `FailureInfo`).
- **Root and stale reads.** `workflow_steps/common/file_source_root.py::resolve_source_root` (export directory or git
  checkout, lease held until the caller's `AsyncExitStack` closes) is shared with `read-from-file` and `read-config`; a
  new file-reading step uses it instead of its own copy. `refresh_repository` (default off) is passed as `refresh` to
  `git_checkout`: off reads the local copy without a pull (`sync="never"`; a missing clone is still made), so a fan-out
  of children each takes the repository lease for a local read only instead of queueing behind a pull
  (a 10-child fan-out used to hit "Timed out after 90s waiting for the lock"). The lease is always taken, so a
  change-request checkout cannot switch the branch under the read, and no DNS lookup runs under it for an existing clone (`open_or_clone(resolve_dns=False)`). A read without a pull is **not** the strict-pull guarantee: the tree may be behind or ahead of `origin`, so the step records a `git_not_refreshed` run event with the commit it read (no git command runs for it, so nothing is checked per device). Refresh with a Pull Git step. `allow_stale_repository`
  only matters while refresh is on (the panel clears it when refresh is switched off). The panel gets both switches from `shared/git-source-config-panel.tsx`
  (`showRefreshToggle`, `showAllowStaleToggle`), and the step's config builder must keep the keys, or the next edit in
  the panel drops them. `services/git/tree_scope.py::async_scope` shields the lock acquisition, so a cancelled step
  releases a lock its worker thread takes late.
- **Shared CSV core.** Parsing and matching live in `backend/services/csv_lookup/` (`parse_csv_rows`, `RowIndex`), which the Ask the Net
  file comparison also uses (`doc/AI_TOOL_CHAIN.md` §61); the step keeps only what is workflow-specific (the root, the device values, the merge,
  the sealed-secret guard). A change to the CSV rules is made there once.
- **Deliberate: no pull, no status check per read.** `refresh_repository` is off by default, also for a stored step that has no such key, and a read runs no git command beyond opening the tree (no pull, no `status`/`diff`). This is a decision, not an omission: a pull or a status check for every device of a fan-out, each under the repository lock, made the children queue past the 90s lock timeout. The price is that the file may be older than `origin`; the step records the commit it read (`git_not_refreshed` run event) and the Pull Git step is how a workflow asks for fresh data. Do not make a pull the default again, and do not add a per-read dirty/ahead check, without changing how fan-out children share one read (for example one read per run).
- **Fan-out.** The step takes every device of the context in one execution, so place it before the fan-out or after the fan-in: the file is then read once. Inside a fan-out each child reads it again under the repository lease; with `refresh_repository` on they can queue behind pulls (use a Pull Git step before the fan-out instead). The Help tab says so.
- Code: `backend/workflow_steps/enrich_attributes/`; frontend `workflow-steps/enrich-attributes/`.

### Age of a config backup: `get-age-of-backup`

Reports how old each device's config backup in a git repository is. Category Configuration Management; read-only (nothing is
written to git or a device).

- **What the date means.** The git date is the newest commit that touched the device's file
  (`services/git/commit_info.py::last_commit_of`, shared with the Ask the Net config-backup reader). A backup commits a file only
  when its content changed (`GitService.commit` returns "No changes to commit" for an empty staged diff), so the date is the last
  *change*, not the last backup run: a stable device that is backed up every night still shows its old date. A config with a
  volatile line (a "last configuration change" timestamp) commits on every run and looks fresh.
- **Backup-check marker (`use_marker`).** To learn when the backup last *ran*, the backup workflow adds a Store in DB step after
  the backup (`storage_key` e.g. `backup_checked`, `content_source: single_attribute`). With `use_marker` on, this step reads the
  record under `marker_storage_key` (rendered per device, like Get from DB) and uses its `updated_at` as `last_checked`.
  `DeviceDataRecordRepository.upsert` always moves `updated_at`, also when the stored value is equal (SQLAlchemy sends no UPDATE for
  an equal JSON value on its own), so a constant marker value is enough. A device with no marker still succeeds: `marker_found` is `false` and `last_checked` / `checked_age_days` are
  `null`. The step also emits one `backup_marker_missing` warning run event per execution (count, the first five
  device names, the key). The count is "devices without a marker of those whose marker was looked up": a device that
  already failed on its backup file is in neither number, a lookup that raised is in the denominator, so a wrong
  key reads "N of N". A marker key that renders empty (an absent attribute in `{...}`) is treated as no marker and is
  never looked up, because Store in DB refuses an empty key. A missing marker is deliberately not a failure; there is no
  `marker_required` switch yet. Because the step succeeds, **a workflow that alerts on age must route the missing
  marker itself**: `null` never matches a comparison such as `{:gt(1)}` (verified against the expression evaluator), so
  route first on `{backup_age.marker_found:equalsIgnoreCase('false')}` (booleans render as `False`) or
  `{backup_age.checked_age_days:isNull()}`, then compare the age, and wire the step's `failure` handle too. See
  `contributing-data/workflow-gallery/check-backup-age.json`. `age_days` is whole days rounded down, so `{:gt(1)}` means
  "two full days or more".
- **Marker content.** The age step only reads `updated_at`, so the backup workflow stores a constant: Store in DB
  `content_source: single_attribute`, `attribute_path: device.name`. `device_data` would keep a second copy of the
  inventory bags under a well-known key. Wire the Store in DB `failure` handle to the error path (the gallery backups send
  it into the funnel before Notify On Error): a failed write leaves no new marker, and the next check would not alert.
- **Result.** Written into a separate bag (`output_bag`, default `backup_age`; not `parsed`, `run_input` or a device field name):
  `age_days` (whole days, rounded down, never negative, a number so a later step can compare it), `last_changed` (ISO UTC),
  `commit_sha`, and with the marker `marker_found` (bool), `checked_age_days` and `last_checked`. One `now` is taken per step run.
- **Per device.** `path_template` is rendered like `read-config` (strict) and contained with `safe_read.contain` (no `..`, no
  `.git`, no symlink). The history is asked for with a **literal** pathspec
  (`:(literal)<path>` in `services/git/commit_info.py`): a plain pathspec treats `[` `]` as a character class, so `DC[1]/r.cfg`
  would report the commit of `DC1/r.cfg`. `git_repository_id` is parsed with `parse_repository_id` (a boolean or `7.9` is refused). A missing file (also one deleted in the working tree but present in history), a file without a commit, an
  unresolved placeholder or an unsafe path fails that device (`backup_not_found`, `no_backup_commit`, `template_unresolved`,
  `unsafe_path`; each with a `FailureInfo`). Bad configuration (no repository, empty template, bad `output_bag`, marker without a key) fails the step.
- **Git root.** `resolve_git_root` (the repository is pulled, `allow_stale_repository` accepts a stale copy; the lease is held
  while the history is read). There is no `refresh_repository` switch. The git reads run in worker threads, one per device.
- **Fan-out.** Read-only, so fan-out safe. Inside a fan-out every child pulls the repository under its lease (the pull is
  deduplicated for a few seconds); place the step before the fan-out when the list is large.
- Code: `backend/workflow_steps/get_age_of_backup/`; frontend `workflow-steps/get-age-of-backup/`.

### Uploading a binary: `upload-binary`

Copies one file (an IOS / IOS-XE image) from a git repository to every device over SCP.
`upload-config` sends *text produced by an earlier step*; the two share
`workflow_steps/common/device_file_upload.py` (per-device concurrency and log lines, the transfer record,
`success`/`failure` split, `socket_timeout`, the remote `verify /md5` / `dir` / `delete` helpers, `RemoteTarget`,
`fail_device_from_exception`) and differ only in the source.

- **Source: one snapshot.** `git_repository_id` (a whole number: `true` / `7.9` are refused,
  `git_repository_loader.parse_repository_id`) + `source_path`, resolved with `file_source_root.resolve_git_root` (strict pull,
  `allow_stale_repository`). `source_file.snapshot_source_file` opens the file **once** through
  `services/git/safe_read.open_file_under` (every component `O_NOFOLLOW`, so a link swapped in after any check is refused),
  checks the descriptor (regular, not empty, at most 4 GiB, not a **Git LFS pointer**), and copies it to a private temporary file while
  computing the MD5; a file whose inode/size/mtime changed during the read fails the step. The MD5, `expected_md5` and the bytes
  sent are therefore one read. The repository lease is held only for that copy and released **before** the first device is
  contacted (so a long transfer neither blocks other git steps nor outlives the lease); the cost is the file size in temporary
  disk space per run. The snapshot is deleted when the step ends.
- **MD5 before and after.** `expected_md5` (the vendor's value) is compared with the snapshot's MD5: a mismatch raises and no device is
  touched. Per device: `dir` (does it exist?) and, if it does, `verify /md5` (identical = not copied again, whatever `overwrite` is;
  different = `file_exists` failure unless `overwrite`). Then Netmiko's SCP `file_transfer` with `verify_file=False`
  (`NetmikoDeviceSession.upload_file(verify_file=...)`: Netmiko's own check has a fixed 300 s timeout), then the step's own
  `verify /md5` with `read_timeout` (5-600 s, default 600). A copy whose checksum is wrong, unreadable or timed out is removed with
  `delete /force` (the message says whether the removal worked), so a failed step does not leave a bootable-looking image behind.
  This holds when the verify itself raises (a dropped connection after the copy): the file is removed, the failed device keeps the rows collected so far, and the message carries the class name only.
  The stored command rows only say "verified" when the device's checksum matched.
- **No inline transfer, on purpose.** Netmiko's inline mode is text only (it reads the file as UTF-8 and types it
  through the CLI with a TCL `puts`); a binary would fail to decode or arrive corrupted, and an image would take
  hours. Without SCP the device fails with the transfer error instead of falling back.
- **Command safety.** `file_system` and `destination_filename` (or the basename of `source_path`) are pasted into `dir`, `verify` and
  `delete` command lines, so a space or line break in either fails the step.
- **Outcomes.** A bad config, an unusable source file or an `expected_md5` mismatch `raise` (nothing was sent); a
  device-level problem (no host, SSH/SCP error, no space, existing different file, checksum mismatch) leaves that device through
  `failure`. A driver exception is stored as its class name plus the structured `FailureInfo`, never the driver text.
- **Fan-out.** Read-only on the repository, and the lease is not held during the transfer, so children do not serialize on it
  (each child still takes its own snapshot).

### Asking the AI: `contact-the-ai`

Sends one prompt per step execution to the AI model (palette category Notify) and stores the answer on
every device in `output_attribute` (`bag.field`, default `ai.response`), so a later step such as
`notify-mattermost` can post `{ai.response}`. The target is validated with the `update-attribute` write rules
before anything is sent (no placeholders, no `device.*`, no reserved bag `parsed` / `run_input`, no secret
path). The run viewer shows the answer, provider, model and target, or the failure reason, under "AI response"
(`metadata["<node id>.ai_response"]`, `step-result-viewer/ai-response-panel.tsx`). Config: `prompt`,
`system_prompt`, `output_attribute`, `max_output_tokens` (1-4096),
`timeout_seconds` (1-600). Outcomes `success` / `failure`. A failed call (AI unavailable, prompt withheld, provider
error, timeout, empty answer) is a whole-step failure: every device leaves through `failure` as FAILED with one
`DeviceError` (`contact_the_ai_failed`, the fixed wording and a `FailureInfo`), so `notify-on-error` has a reason to report;
`success` is answered empty and no answer is stored on any device.

- **Whose AI settings:** a background run has no interactive user, so the step uses the settings (provider,
  key, sharing switches, proxy) of the service user named by the operator in `WORKFLOW_AI_USER`, through
  `AiSettingsService.require_runtime_config`. Unset, AI disabled by the operator, or not configured: the step
  ends on `failure` (`permission_denied`), nothing is sent.
- **What may be sent:** every placeholder is checked against the service user's sharing switches **before** it is
  resolved, with the interactive assistant's rules (`services/ai_assistant/data_sharing.py`, S5-03; checks in
  `workflow_steps/contact_the_ai/prompt.py::check_path`). The operator's `AI_ALLOWED_DATA` is already ANDed in
  by `require_runtime_config`. `device.name` / `platform` / ..., a Nautobot basic attribute (`name`, `role`,
  `location`, ...), `{devices}` and `{run_summary}` (counts per device status plus failed device names with error
  codes, never error text; `build_run_summary` in `workflow_steps/common/run_message_template.py`, also usable
  in `notify-mattermost`) need *Inventory*. `device.hostname` / `primary_ip4` and the Nautobot address group
  (`hostname`, `serial`, `asset_tag`, `interfaces`, ...) need *Addresses*, `custom_fields` *Custom fields*,
  `config_context` *Config context* (each of these needs *Inventory* as well, as in the assistant). A Nautobot
  attribute in none of those groups (`comments`, ...) is never sent. Any other bag (`custom`, `parsed`, `ise`,
  run inputs, ...) needs *Inventory* **and** *Content*, and a key named like one of the groups below it is
  withheld without its switch. A placeholder the policy withholds ends the step on `failure`
  (`permission_denied`, a fixed message naming the placeholder and the switch) and nothing is sent. A prompt
  without placeholders needs no switch. Scalars are always read with `reveal_secrets=False`.
- **Whole bags and other dicts (`{nautobot}`, `{nautobot.location}`, `{parsed.x.y}`):** in this step only, a path
  that resolves to a dict or list is rendered as compact JSON (`workflow_steps/contact_the_ai/prompt.py`); every
  other step still renders it as an empty string. The same switch rules apply; a whole `{nautobot}` is filtered
  like the assistant filters it (withheld attribute names are listed under `withheld`), and below any other bag
  the withheld category keys are replaced by `{"not_shared": ...}`. It then goes through
  `Redactor.tokenize_data` (secret-named keys and sealed envelopes become tokens), and each value is cut at
  20 000 characters. **Risky:** a bag mixes addresses, custom fields, config context and whatever upstream
  steps stored, so more data leaves the network than a named field would, and redaction is best-effort.
  **Expensive:** a device bag with interfaces is tens of thousands of characters, paid on every run. Prefer
  single fields (`{nautobot.role}`) and send a whole bag only when the model needs it.
- **Redaction:** the rendered prompt and system prompt always go through `Redactor` (config-style secrets,
  the service user's visible credential values, addresses unless the *Addresses* switch is on). If the
  credential values cannot be loaded the step fails closed. Redaction is best-effort, like the assistant's
  (`doc/ai_integration/AI_ASSISTANT.md` §4.3). With the addresses switch off, the operator's
  `AI_ADDRESS_MASKING` (`tokens` / `map` / `auto`, `AI_ADDRESS_MAP_FILE`) decides whether an address becomes a
  token or a reversible fake address (§21 "Address masking"); fake addresses the model repeats are mapped back to
  the real ones in the answer and in the stored attribute, exactly those that were sent, never a neighbour or a
  whole prefix. Tokens and secrets in the answer are never restored.
  The viewer metadata records the mode and how many addresses were hidden, never the addresses.
- **Safety of the answer:** the model gets no tools and a built-in instruction to treat run data as data. The
  answer is cut at 10 000 characters and `@channel` / `@all` / `@here` are defused. The prompt is cut at
  100 000 characters.
- **Failures** are a closed-vocabulary `FailureInfo` (`auth_failed`, `rate_limited`, `server_error`, `timeout`,
  ...) plus one fixed sentence per kind. The provider's own text (it can carry a configured base URL) is never
  stored in the run, shown in the viewer or logged. Wire a fallback `notify-mattermost` to the `failure` outcome.
- **No device:** the step sends nothing and stores nothing (there is no device to attach the answer to); the
  summary and the viewer say "skipped".
- **Service user lookup** is case-insensitive, like login.
- **Fan-out:** place it after Fan In (or at the end of a non-fanned workflow) for one call per run; inside
  fan-out children it calls the model once per child.

### Structured failure on `DeviceError`

When a step fails a device, pass a `FailureInfo` (`models/failure.py`) as
`DeviceError.failure` in addition to the free-text `message`. It records *why* in a closed
vocabulary (`phase`, `kind`, `attempts`, `elapsed_ms`, `hint`) with no free text, so the AI
assistant shows it without the user's content opt-in while the `message` stays class C
(`doc/ai_integration/AI_ASSISTANT.md` §19). Netmiko failures arrive already classified:
`NetmikoConnectionError.failure`, `CommandResult.failure`, `ConfigResult.failure` and
`DeployResult.failure` (`services/network/netmiko/failure.py`); copy them with
`failure_from_exception(exc)` or `result.failure`. Never add a free-text field to `FailureInfo`.
Done for `run-command`, `get-device-configs` and `store-for-report` (unusable values and duplicate device names are `config` / `bad_request`; database and unexpected errors are `internal` / `internal_error` with only the exception class, and their run message is a fixed sentence); `route-to-agent` records every failure in phase `agent` (kinds `agent_offline`, `agent_handler_error`, `payload_too_large`, `output_rejected` plus `timeout`, `auth_failed`, `invalid_response`, `bad_request`, `internal_error`); other steps and sources still record only text.

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

This section is the contract of `DeviceSessionPool` (`services/network/netmiko/session_pool.py`); the code comments
that speak of the pool refer to it.

**Who uses the pool.** Eight steps open SSH sessions through it: `run-command` (Run Command), `get-device-configs` (Get
Configs), `deploy-rendered-template` (Deploy rendered Template), `merge-config` (Merge Config), `upload-config`
(Upload Config), `upload-binary` (Upload Binary), `collect-client-data` (Collect Client Data) and `discover-network`
(Discover Network). `login-successful` (Login Successful) uses the pool's disposable probe only (below). An SSH step
passes the pool on as `NetmikoService(pool=device_sessions)`; a non-SSH step takes the `device_sessions` argument and
never uses it (import `DeviceSessionPool` under `TYPE_CHECKING`).

**Scope and ownership.** One pool per execution segment: a phase-1 walk (`hatchet/workflows/workflow_run/phase1.py`),
a phase-4 post-join resume (`workflow_run/aggregation.py`) or a fan-out child (`hatchet/workflows/device_group_execution.py`).
`StepRunner` creates it and injects it into every executor call as `device_sessions`; whoever creates the `StepRunner`
calls `await runner.close_device_sessions()` in a `finally` (those three call sites). Never keep `device_sessions` or a
session object beyond the `execute()` call.

**Reuse.** A session is keyed by `(host, device_type, credential_reference)`: the credential's name, never the
username or password, so no secret is part of a key or a log line. A step that reaches the same device with the same
credential as an earlier step of the segment reuses the live socket; no canvas or UI change is needed. The pool checks
the host policy (`core.safe_hosts.validate_inventory_host`) before any session exists.

**Invariant.** `run_on_device(op=...)` is the only way to touch a pooled session: it takes the session's lock, connects
or reconnects lazily (the `retry` policy applies to the connect only, never to `op`), runs `op` on the pool's thread
executor and releases. Every `op`, and every public `NetmikoService` method, must leave the session in privileged-exec
base state: config mode exited and no interactive prompt pending, also after an error, because the next step may get
the same live session. With `debug=True` the pool checks `check_config_mode()` after the `op` and logs a warning when a
step left config mode open. `run-command` in `config_mode` uses the same `NetmikoService.deploy_config()` path as
`deploy-rendered-template` and so inherits the guarantee; `merge_running_config` leaves the session at the base prompt
or, on an error, to be reconnected on the next use.

**Fan-out boundary.** Sessions never cross a Hatchet parent-to-child task boundary: each fan-out child has its own
pool, and the orchestrator opens no session while it dispatches the children, so there is nothing to suspend before
a Wait & Run approval gate. A workflow that logs into a device both before and inside a fanned-out branch pays one
extra login per device at the boundary: rare by construction, accepted.

**Cancellation.** A cancelled step does not detach the pool from the thread that still uses the session:
`suspend()`, `close()` and `close_host()` wait up to 60 s for that operation before they disconnect.

**Ending sessions early.**
- `suspend()` disconnects every live session but keeps the pool usable (the next use reconnects); `close()` calls it.
  Nothing calls it directly today (its only caller, the per-node debug pause, was replaced by `stop-here`, see
  [Fan-out execution](#fan-out-execution)).
- `close_host(host)` disconnects and forgets every session of one host. `discover-network` logs each visited device out
  when its visit is done instead of holding the socket until the segment ends; a later use of the host connects again.

**Login probe.** `login-successful` must prove a real new authentication even when a live pooled session for the same
key exists. `probe_login()` opens a disposable session, checks it is alive and disconnects; it never reads, locks or
replaces a pooled session, so a failed probe still leaves the pooled session for a rollback step.

**Switching pooling off.** `NETMIKO_SESSION_POOLING=false` (`settings.netmiko_session_pooling`) restores a fresh
session per call (connect, use once, disconnect) without a code change.

Tests: `tests/unit/test_device_session_pool.py` (the pool), `test_netmiko_service_pool_integration.py` (two calls with
the same key reuse one session), `test_step_real_session_pool*.py` (each SSH step against a real pool and a fake session).

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

The snippet shows one shim call. **A step that runs the same operation on many devices does not call `run_job()`
per device:** it uses `workflow_steps/common/pyats_batch.py::run_batched`, which groups the devices by pyATS source,
cuts them into chunks (`DEFAULT_CHUNK_SIZE` 5; the job timeout grows with the chunk), calls `run_job()` once per chunk
and runs at most as many chunks at once as the shim's `/health/pyats` limit allows. A failed chunk (network error,
timeout, rejected request) fails only the devices of that chunk. `get-pyats-running-config` (Get & Parse Config) and
`get-pyats-snapshot` (Get Snapshot) use it. Two steps call the shim directly on purpose:
`compare-pyats-snapshot` (Compare Snapshot) calls `/v1/diff`, not a job, and `configure-replace-config`
(Configure Replace Config) runs up to three strictly ordered jobs per device on one CLI session
(`configure_replace_config/shim_jobs.py`).

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
than hanging, and a device is failed if the transcript carries `%Error opening`, a CLI refusal or a `%Warning`
line (the last two follow `fail_on_cli_error`, default on; see "Config push"). It reuses the Run Command backend (`NetmikoService` / `DeviceSessionPool`,
`resolve_config_reference` + `resolve_ssh_credential`, `resolve_connection_device_type`)
and exposes only `source_filename`, credentials, `network_driver_override`, `fail_on_cli_error` and
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
`parsed.<node_id>.batfish_extract_facts.parsed.TACACS.TACACS_Servers[address=10.0.0.5]`
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
- `update-attribute` also accepts these placeholders in its **destination** path (inside a
  `[...]` selector only); an unresolved one skips that write for the device. Not supported:
  nested `{…}` inside the `{path | default('x')}` value expressions used by steps such as
  Update Device. For anything more complex use `render-jinja-template`.

### Writing to a list item

`update-attribute` (`workflow_steps/common/attribute_write.py`) can write **into** a list of
objects with the same `<key>[<field>=<value>]` selector, e.g.
`nautobot.interfaces[name=Ethernet0/0].mac_address`. The item whose `<field>` equals `<value>`
is copied and updated; when there is none, `{<field>: <value>}` is **appended** and the leaf is
set on it, so repeated writes for the same name build up one item. Differences from reading:
`<field>` must be a flat key (not a sub-path), the value must not be empty or contain
`[ ] =`, the selector must be followed by the field to write, and the target must be a list
(or absent). A `.` or `/` inside the value is fine (`Gi0/0.100`). Update Device reads such a
bag with `interfaces_source: nautobot_origin`. Two selector forms the **reader** accepts are
refused by the writer with a `ValueError`, because the write would otherwise succeed in a place the
reader never looks: a dotted filter field (`interfaces[lag.name=Po1]`) and a literal position
(`interfaces[0]`). Select the item by a flat field instead.

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
  location — `update-attribute`, `log-message`, `add-ip-to-nautobot` — must pass
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
`get-ise-devices`, `get-catalyst-center-devices`, `get-aci-devices`, `get-from-list`, `get-from-user`) may enable
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
shared `workflow_steps/common/fan_out.py::inventory_metadata` helper (it calls `build_fan_out_metadata`) when `enabled`
is true. It returns the context metadata with the step's `{node_id}.<key>` entries; `.success` carries `_fan_out`, `.base`
does not (a failure branch that carries stub devices uses `.base`). All ten inventory steps — `get-nautobot-devices`,
`get-virtual-chassis`, `get-git-devices`, `get-ise-devices`, `get-catalyst-center-devices`, `get-aci-devices`, `get-from-list`,
`get-from-user`, `get-from-config`, `get-from-agent` — call it; do not duplicate the sanitisation inline in a new inventory
step. `get-aci-devices` and `get-catalyst-center-devices` are one body, `common/controller_inventory.py::run_inventory_step`,
with a `ControllerInventory` descriptor per controller; the fact and topology selectors share `fact_entries.parse_name_list`.

**Failure outcome and fan-out.** Fan-out starts every child from the inventory step's `success` outcome only, so
an inventory step that reports devices on a `failure` outcome (today `get-git-devices` for primary-IP data
problems) cannot deliver them when fan-out is enabled; it fails the step instead.

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
| `get-device-configs`, `run-command`, `run-catalyst-center-command`, `get-catalyst-center-configs`, `get-catalyst-center-details`, `get-aci-details`, `get-aci-policy`, `find-aci-endpoints`, `compare-aci-subnets`, `get-catalyst-center-topology`, `get-catalyst-center-health`, `merge-config`, `get-nautobot-attributes`, `get-device-location`, `get-virtual-chassis`, `split-virtual-chassis`, `render-jinja-template`, `log-message`, `route-on-attribute`, `generate-password` | ✅ | Per-device compute, no shared mutable sink. |
| `get-next-free-ip` | ⚠️ | Read-only (`/ipam/prefixes/{id}/available-ips/`), nothing is reserved in Nautobot. Devices of one execution get distinct addresses because they are served in order from one list, but fan-out children and parallel runs each read the same free list and can receive the same address. Place it before the fan-out step's children or after a **Fan In**, and create the address (**Add IP to Nautobot**) before another run reads the prefix. |
| `add-ip-to-nautobot` | ✅ | Get-or-create through the shared `IPManager`: an address that exists is reused, and a concurrent creator of the same address or parent prefix is resolved by re-reading it, so fan-out children and sibling branches converge on one object. The addresses themselves still have to be distinct: take them from **Get Next Free IP** (which does not reserve them) and see its row. |
| `update-nautobot-ip` | ✅ | Idempotent PATCH of the address each device names (`ip_id`), sent only when a value differs. Safe in fan-out children and sibling branches while the devices name different addresses; two devices naming the same address with different values race (last write wins). |
| `update-nautobot-vlan` | ✅ | PATCH of the VLAN each device selects (`vlan_id` or `vid` + `vlan_group`), sent only when a value differs. Devices that resolve to one VLAN with the same values share one write and the same result; devices that ask for different values of one VLAN are written one after the other (the later value wins); different VLANs are written concurrently. Two *runs* on one VLAN still race, and the `add` / `remove` location modes read before they write (not atomic). |
| `update-nautobot-prefix` | ✅ | PATCH of the prefix each device selects (`prefix_id` or `prefix` + `namespace`), sent only when a value differs; locations are assignment rows. Devices that resolve to one prefix with the same values share one write and the same result; devices that ask for different values of one prefix are written one after the other (the later value wins); different prefixes are written concurrently. Two *runs* on one prefix still race, and the `add` / `remove` location modes read before they write (not atomic). |
| `remove-from-nautobot` | ⚠️ | Deletes the device each context device names by its own UUID. Within one execution the devices run one after another when `remove_ip_addresses` is on, so an address shared by them is removed by the last holder. Fan-out children and sibling branches run in separate executions and cannot see each other: two holders of one address removed there can both keep it, leaving it unassigned. Place the step after a **Fan In** when devices share addresses. Two devices naming the same UUID: the second fails `device_not_found`. |
| `git-status` | ✅ | Read-only inspection (plus an optional `git fetch`) under the per-repository lock, so concurrent callers are serialised, not corrupted. Its result is per repository, not per device — inside a fan-out branch it re-checks the same repo once per child, so prefer a single check before the fan-out inventory step's children or after a Fan In. |
| `start-workflow` | ⚠️ | Starts one run for all devices it receives, or one per device (`max_runs`), and optionally polls them for up to 600 s. Two concurrent callers start two sets of runs, so inside a fan-out child it starts runs per child, each waiting in its own worker slot: place it before the fan-out or after a **Fan In**. See "Starting another workflow: `start-workflow`" below. |
| `send-mail` | ⚠️ | Sends one email per execution and holds no shared state, so concurrent callers never corrupt anything — but inside a fan-out child branch it sends **one mail per child**. Place it after a **Fan In** node (or at the end of a non-fanned workflow) for one mail per run. Mail is sent only through the SMTP server an administrator configured under Settings → Mail (server, port, security, login credential and sender address are not step settings; the admin's `allowed_recipient_domains` apply). The step config keeps `to`, `subject` and `body`. |
| `add-nautobot-metadata` | ✅ | Writes shared Nautobot reference data (a Location / Device Type), but as get-or-create: an existing object is reused, a duplicate-key error from a concurrent creator is resolved by re-reading it, and devices resolving to the same object share one call within a step run. |
| `collect-client-data` | ✅ | Each device's data is one collection keyed by (run uuid, device name) in the `client_*` tables; the write replaces that device's rows for the run (a retry or loop does not duplicate them) and prunes the device's older collections, so fan-out children and sibling branches that handle disjoint devices never touch the same rows and no Fan In is needed. Database writes of one execution are serialised, so a large fan-out does not take a pooled connection per device. Two devices of one step with the same name fail the second (`duplicate_key`). See `doc/CLIENT_DATA.md`. |
| `get-catalyst-center-client-data` | ✅ | Same storage rules as `collect-client-data` (one collection per run uuid and device name in the `client_*` tables, replaced on retry), but the data comes from one Clients API query per device on the controller (at most 5 in flight per step), so each fan-out child queries only its own devices. Two devices with one name fail the second (`duplicate_key`). See `doc/CLIENT_DATA.md`. |
| `store-for-report` | ✅ | Appends rows to the report tables keyed by (dataset, device name, collection), so fan-out children and sibling branches that handle disjoint devices never touch the same rows and no Fan In is needed. The same step writing a dataset for the same device again in a run (retry, loop) replaces its earlier rows; a **different** step writing the same dataset for the same device fails that device (`node_id` is recorded per row): put all fields of a dataset into one step, or use one dataset per step. A path that matches nothing stores `null` (right for an optional attribute, but also what a mistyped path does): when a field is empty for every stored device in `device` mode, the step stays `success` and its summary names the field (`field(s) 'ip' had no value for any of 2 device(s); check the attribute path`). Rows are never deleted by the step; see `doc/REPORTS.md`. |
| `store-artifact` → `destination: filesystem` | ⚠️ | Safe **only** if `filename_template` is device-unique. A fixed name or colliding `{run.timestamp}` makes concurrent callers overwrite/race. |
| `store-artifact` → `destination: git`, `backup-aci-config`, `git-clone`, `git-pull`, `git-push`, `open-change-request` | ⚠️ | All open **one shared on-disk working tree per git repository** (`load_git_repository` → single `path`). A per-repository advisory lock (`services/git/repo_lock.py`, Redis `SET NX EX`; fail-soft only when Redis is unavailable, a lock still held after the 90 s acquire timeout fails the step) serialises concurrent callers against the *same* `GitRepository` — whether two runs, fan-out children (cross-process), or two independent sibling branches in one run (same process) — so the working tree itself is **not** corrupted. It does **not** make two concurrent callers collapse into one logical operation, though: each still opens its own commit (and, for `open-change-request`, its own branch/change-request row), which is rarely what you want. Place git-touching steps after a **Fan In** node (fan-out) or wire an explicit dependency edge (independent branches) so exactly one export/commit/change-request comes out, not N. |

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
  `name`, `ip`, `name,ip` or `name,ip,network_driver` line per device. `devices_input` names that
  input; the step fills it with one `name,ip[,network_driver]` line per device it received
  (`_device_line`: bare primary IP, a name containing a comma or line break is replaced by the IP; the
  device's Netmiko driver rides along (resolved from `network_driver` and `platform` with
  `resolve_netmiko_device_type`; a value Netmiko rejects is left out so it cannot fail the whole child
  list, and the child's default applies); a device with neither name
  nor IP fails with `no_device_identity`).
  With no `devices_input` the target is called without devices. No engine special case, nothing in
  `WorkflowRun.device_ids`: the same workflow can be run by hand, scheduled, or called.
- **Network driver without Nautobot.** Get from List (per row `network_driver`) and Get from User
  (`name,ip,network_driver` per line, step-level `default_network_driver`) set
  `DeviceContext.network_driver`, default `cisco_ios` (`workflow_steps/common/device_list.py`,
  validated with `resolve_netmiko_device_type`, stored as the canonical type (`ios` -> `cisco_ios`) and
  defaulted before duplicates are removed; unknown drivers fail the step naming the row/line).
  A step-level override such as Run Command's `network_driver_override` still wins.
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

### Discovering the network: `discover-network`

`discover-network` (display name "Discover Network", `artifact_type: persistent_artifact`, outcomes `success` /
`failure`) walks across the network through CDP. The devices that arrive in the context are the **seeds**. Each
device is logged into over a pooled SSH session, `show cdp neighbors detail` is read (TextFSM), and the session is
closed again (`DeviceSessionPool.close_host`) before the next level starts. Code: `backend/workflow_steps/discover_network/`
(`crawler.py` is the pure breadth-first walk, `executor.py` wires SSH, credentials and outcomes).

- **Following is opt-in.** `follow_neighbors` (default off) logs into the devices CDP reports; off, only the seeds are
  visited and the neighbours are listed. It needs `permitted_prefixes`: IPv4 CIDR, at most 50, each /8 or more
  specific, never overlapping loopback, link-local, multicast or reserved space (`scope.parse_prefixes`).
  A neighbour is queued only if it has a management IPv4 address, advertises router or switch
  (`follow_only_infrastructure`, default on), lies in a permitted prefix, passes `core.safe_hosts.validate_device_host`,
  is Cisco IOS / IOS-XE / NX-OS (guessed from the model in the CDP platform string, with or without the word "cisco"; if that is not usable, from
  the software line of the detail output, so a virtual switch that reports `Platform: Linux` but
  `Cisco IOS Software [IOSXE], Linux Software (...)` is logged into as IOS-XE; IOS-XR is never guessed;
  `network_driver_override` only when both are empty) and `max_devices` (default 50, seeds included) / `max_depth`
  (default 5) allow it. The operator switch `DISCOVER_NETWORK_FOLLOW_ENABLED` (default on in development only, allowed
  in production) is also required, checked before any login (`scope.ensure_following_allowed`): the devices found are
  not from the inventory. It is deliberately not `ALLOW_NETMIKO_ARBITRARY_HOSTS`: startup refuses that one outside
  development. A followed host is checked against the prefixes and `validate_device_host` once more right before the
  login (`executor._make_visit`). **Residual risk:** CDP is unauthenticated, so a device inside the prefixes (or a
  spoofed advertisement) can name any management address in them and is then offered the step's SSH credential. Keep
  the prefixes narrow and use a read-only credential.
- **Management IP lookup** (`resolve_management_ip`, default on; `nautobot_source_id`). CDP reports an *interface*
  address of a neighbour, which is often not the address a device accepts logins on. For every neighbour that could be
  followed (follow on, infrastructure, supported platform; not phones or hosts) `nautobot_lookup.ManagementIpLookup`
  looks the **name** up in Nautobot (exact, ignoring case, start of a full name, then the first label of a qualified
  name) and uses the device's `primary_ip4`; if that finds nothing usable, it looks up the reported **interface
  address** and uses the owning device's name and `primary_ip4`. An ambiguous answer (several devices) is never
  guessed. The crawler swaps the address *before* the scope check, the duplicate check and the login
  (`crawler._resolve_neighbors`), so the prefixes, the host policy and the identity rule apply to the address that is
  dialled; two interface addresses of one device collapse to one visit. Records carry `reported_ip` (the CDP address)
  and `ip_source` (`cdp`, `nautobot_name`, `nautobot_ip`); the step summary has `management_ip_lookup`: `on`, `off`,
  `no_source` (on, but no Nautobot source chosen: the step runs on the CDP addresses so older workflows keep working)
  or `unavailable` (Nautobot failed: CDP addresses used). A configured but unusable source (missing token or URL) is a
  `ValueError` at start. Reads go through `NautobotServiceClient` (`strict=False`) like `get-virtual-chassis`.
- **Identity** is the management IP. A name recognises a device only when there is no IP to compare: a seed given by
  host name (its SSH host name decides, the display name only on an exact match) and a neighbour that reported no
  address. Two qualified names that differ (`core1.a.example`, `core1.b.example`) are two devices. A neighbour first seen
  without an address and later with one is followed, and the old `no_management_ip` row is dropped. Names, platform
  strings and ports from CDP are attacker-influenced text: control characters removed, cut to 100 characters, never used
  to build a command or a path.
- **Closed reasons** a neighbour was not logged into (`seen_not_visited[].reason`): `follow_disabled`,
  `no_management_ip`, `not_infrastructure`, `out_of_scope`, `unsupported_platform`, `limit_reached`, `unreachable`,
  `login_failed`.
- **Outcomes.** A neighbour that cannot be reached never fails the step; it is listed with its reason. A device that is
  reached but has CDP off (or no table) is still *visited* (`cdp_status` says why). A **seed** that cannot be visited
  leaves through `failure` (`unreachable`, `login_failed`, `unsupported_platform`, and for a reached seed without a
  CDP table `cdp_not_enabled`, `cdp_not_supported` or `cdp_no_output`; its `parsed.<node id>.discovery.cdp_status` is
  kept, and the crawl record is on both exits). A seed given twice (same address, or the same host name) is visited once and the duplicate
  follows its twin: it passes through on `success` (`discovery.skipped: duplicate_seed`) when the twin did, and fails with
  the twin's code and `FailureInfo` when the twin failed.
- **Reading the CDP output** is shared with `collect-client-data` (`services/parsing/neighbors.py`:
  `classify_neighbor_table` decides rows / empty / refused / protocol off / unparseable, `decode_textfsm_output`, the
  supported Cisco device types). Each step keeps its own status vocabulary: a switched-off CDP is `not_enabled` here (the
  seed fails with `cdp_not_enabled`) and `not_supported` in `collect-client-data`. The row mapping stays per step (different
  fields and sanitising). The Nautobot name ladder of `nautobot_lookup.py` is a deliberate copy of the library's
  `_NAME_LOOKUPS`; both carry a comment that says so.
- **Result.** `success` carries the seeds and every device that was logged into; discovered devices are new
  `DeviceContext`s (`source: "discover-network"`, `primary_ip4` = the address used, `network_driver` = the guessed type).
  Each has `parsed.<node id>.discovery` (`depth`, `discovered_from`, `cdp_status`, `neighbors`); the step-level lists
  (`visited`, `seen_not_visited`, `edges`, `limits_hit`, `truncated`) are in `metadata["<node id>.discovery"]`, bounded
  (500 seen, 1000 edges, 200 neighbours per device). The run page shows the step-level record as a "Network discovery"
  panel in the step result (`step-result-viewer/discovery-panel.tsx`: visited devices, seen-not-visited with the reason,
  links, a warning for `limits_hit` / `truncated`) and hides it from the raw Metadata list. To find devices Nautobot does not know, wire
  `exists-in-nautobot` behind it, with strategy `interface_ip` (any interface address; the address logged in to is often a loopback,
  not the primary IP) or `primary_ip`.
- **Fan-out.** A walk is one connected crawl: with fan-out on the seeds every child walks alone and revisits shared
  devices. Use one seed or no fan-out before this step.
- Not built: LLDP fallback, non-Cisco platforms, per-device credentials, stored history of walks. Not run against real
  devices yet (unit tests with a scripted Netmiko only): the CDP detail fields per platform and the platform-string
  mapping are from sample output and general knowledge.

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

11. **AI step aliases** — when you remove, disable or rename a step, open the glossary tab
    "Workflow step aliases" and delete or re-point aliases that name it (a stale alias is ignored
    by the assistant, so nothing breaks, but it stays in the list). A new step's `id` or `name`
    that equals an existing alias word wins over the alias. No code change is needed.
