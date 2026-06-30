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

### Artifact types

| Value                   | Meaning                                      |
|-------------------------|----------------------------------------------|
| `inventory_selector`    | Selects or resolves target devices           |
| `configuration_retrieval` | Reads device state or configuration        |
| `command_execution`     | Runs CLI commands on devices                 |
| `control_flow`          | Branches or gates the execution path         |
| `persistent_artifact`   | Stores durable output (backups, reports)     |

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

The function must return one or more `StepOutcome` values. Each outcome carries a
`WorkflowContext` snapshot for downstream routing via `sourceHandle` on canvas edges.
Outcomes are persisted to `workflow_step_results` and used by `StepRunner` when
assembling input context for dependent steps.

Raise a `ValueError` for configuration errors (bad input, missing field). Raise a
`RuntimeError` for unexpected execution failures. The `StepRunner` catches all
exceptions, marks the step failed, and skips remaining steps.

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

External code (routers, other services) must never import `workflow_steps` packages
directly. The `StepRunner` is the only authorised caller.

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
        "device_filter": {"logic": "AND", "negate": False, "id": "root", "items": []},
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
};
```

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
| `requires`        | Whether a target (input) handle is shown      |

**Sizing:** all nodes are `w-80` × `h-32`. Never add per-step width/height overrides.

**Outcome colours:** the shared renderer applies green to `success` / `match` / `pass` and
red to `failure` / `fail` / `error` / `mismatch`. Name outcomes accordingly in
`registry.yaml` so branching edges are visually consistent.

**Optional icon override:** if the default `artifact_type` icon is not distinctive, add one
entry to `nodeIconsByKind` in `workflow-node.tsx` — do not fork the node layout.

Full rules (title wrapping, outcome palette, fan-out badge, anti-patterns): see
`doc/WORKFLOW-STEPS-STYLE_GUIDE.md` → **Canvas node (React Flow)**.

---

## Fan-out execution

An **inventory step** (`get-nautobot-devices`, `get-git-devices`) may enable
**fan-out**: instead of running the whole workflow once with every device sharing a
single context, each device — or each chunk of devices — is processed as an independent
Hatchet **child workflow**. This parallelises per-device work and isolates failures.

### How it is configured

Fan-out lives in the inventory step's `pluginConfig.fan_out`:

```json
{
  "enabled": true,
  "mode": "per_device",   // "per_device" (1 child per device) or "chunked"
  "chunk_size": 1,         // devices per child when mode == "chunked"
  "max_concurrency": 0     // 0 = unlimited, 1 = sequential, N = N children at a time
}
```

The inventory executor copies these values into `context.metadata["_fan_out"]` when
`enabled` is true (see `get_nautobot_devices/executor.py`).

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
                — for that group's device subset, WITHOUT writing WorkflowStepResult rows.

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
  result may be `partial`; the run is `failed` only when a post-join step raises.

### Fan-out merge (`services/workflow_context/merge.py`)

`merge_fan_out_contexts` folds disjoint child contexts back together:

- **devices** — plain union (children own disjoint device sets).
- **metadata lists** (e.g. `{node}.stored_artifacts`) — concatenated across children.
- **metadata scalars/dicts** (e.g. `{node}.git_export`) — **first child wins** on
  conflict, silently. A per-run aggregate value cannot be reconstructed this way.

### Writing fan-out-safe steps

When you author a step, assume it may run concurrently in many child workflows against
the **same external resources**. A step is fan-out-safe when it:

- writes only to **per-device-unique** destinations (e.g. a `filename_template` keyed on
  `{device.name}`), and
- holds **no shared mutable external state** that multiple children mutate at once.

| Step kind | Fan-out safe? | Why |
|-----------|---------------|-----|
| `get-device-configs`, `run-command`, `get-nautobot-attributes`, `render-jinja-template`, `workflow-log`, `route-on-attribute` | ✅ | Per-device compute, no shared mutable sink. |
| `store-artifact` → `destination: filesystem` | ⚠️ | Safe **only** if `filename_template` is device-unique. A fixed name or colliding `{run.timestamp}` makes concurrent children overwrite/race. |
| `store-artifact` → `destination: git`, and `git-clone` / `git-pull` / `git-push` | ❌ | All open **one shared on-disk working tree per git source** (`load_git_source_repository` → single `path`). Concurrent children race on `index.lock`, produce N single-file commits instead of one, and reject non-fast-forward pushes. |

**Guidance for git-backed exports under fan-out:** place a **Fan In** node between the
per-device branch and the git/store steps. The per-device work (configs, commands,
templates) runs in parallel children; the `store-artifact (git)` / `git-push` steps run
once on the merged context after the rejoin — one pull, one commit, one push, no
`index.lock` races. `max_concurrency: 1` only serialises children and still produces N
commits, so it is not a substitute for the fan-in node.

> If you add a step that mutates a shared external resource, either require it to sit after
> a fan-in node, document its fan-out behaviour in `registry.yaml`, and/or prefer
> per-device-unique writes.

---

## Adding a new step — checklist

1. **Backend package** — create `backend/workflow_steps/{step_id}/`:
   - `__init__.py` (empty)
   - `executor.py` with `async def execute(*, config, context, run, artifact_service, node_id)`
   - `config.py` with `def get_config() -> dict` (if the step has configuration)
   - `models.py` with step-specific Pydantic models (if needed)

2. **Dispatch table** — add one import and one entry to `services/execution/step_registry.py`

3. **Registry** — add an entry to `workflow_steps/registry.yaml`

4. **Frontend ConfigPanel** — create `frontend/src/components/features/workflow-steps/{step-id}/index.tsx`
   (config UI only; canvas rendering is shared — see [Canvas node appearance](#canvas-node-appearance))

5. **UI registry** — add an entry to `frontend/src/lib/plugin-ui-registry.ts`

6. **Canvas icon (optional)** — add a `nodeIconsByKind` entry in `workflow-node.tsx` when the
   default `artifact_type` icon is not appropriate; do not add a custom node render branch

7. **Fan-out review** — confirm the step is fan-out-safe (see [Fan-out execution](#fan-out-execution)).
   If it writes to a shared external resource, make the write per-device-unique or
   document the constraint.
