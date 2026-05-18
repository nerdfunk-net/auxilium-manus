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
└── device_selection/             # One directory per step (snake_case)
    ├── __init__.py
    └── preview.py                # Step-specific backend logic

frontend/src/
├── components/features/
│   └── workflow-steps/           # Frontend root — one sub-directory per step
│       └── device-selection/     # Matches the step id (kebab-case)
│           ├── index.tsx         # Exports the PluginUIComponent (ConfigPanel)
│           └── preview-dialog.tsx
└── lib/
    └── plugin-ui-registry.ts     # Maps step id → PluginUIComponent
```

### Naming conventions

| Layer    | Convention   | Example                  |
|----------|--------------|--------------------------|
| Backend  | `snake_case` | `device_selection/`      |
| Frontend | `kebab-case` | `device-selection/`      |
| Step id  | `kebab-case` | `"device-selection"`     |

The `id` field in `registry.yaml` is the single source of truth that links the backend
directory, the frontend directory, and the UI registry entry.

---

## The Registry (`backend/workflow_steps/registry.yaml`)

Every step must have an entry in the registry. The backend reads this file once at
startup and exposes it via `GET /api/workflow-steps`. The frontend fetches it on boot
to populate the canvas palette.

### Entry structure

```yaml
- id: device-selection            # kebab-case, unique, immutable
  name: Device Selection          # Human-readable label shown in the UI
  description: >                  # One-sentence description for the palette tooltip
    Select one or more target devices from the inventory.
  artifact_type: inventory_selector  # Semantic category (see below)
  directory: device_selection     # Sub-directory inside backend/workflow_steps/
  enabled: true                   # false hides the step from the palette

  metadata:
    mandatory_input:              # Data that MUST arrive from a predecessor step
      - name: selected_devices
        description: Devices selected for configuration retrieval.
        data_type: device_list
        required: true

    configuration_input:          # Values the user sets in the config panel
      - name: credential_reference
        description: Reference to credentials stored in the backend.
        data_type: credential_ref
        required: true

    supported_output:             # Data this step emits to successor steps
      - name: configuration
        description: Running configuration of the selected devices.
        data_type: text_map

    outcomes:                     # Named exit paths used by condition edges
      - name: success
        description: Step completed without errors.
      - name: failure
        description: Step encountered an error.
```

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

Every step that requires server-side logic adds a Python sub-package under
`backend/workflow_steps/<step_directory>/`.

- The package must contain an `__init__.py`.
- Business logic lives in dedicated modules within the package (e.g. `preview.py`,
  `executor.py`).
- The package must **not** be imported directly by routers or services outside the
  `workflow_steps` package. All external access goes through the router in
  `backend/routers/workflow_steps.py`.

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
| `onPreview`| `() => void`                            | Optional — trigger a preview action      |

### Plugin config contract

A step may optionally expose default configuration values by providing a
`config.py` module in its backend package:

```python
# backend/workflow_steps/device_selection/config.py
def get_config() -> dict:
    return {
        "inventory_source": "nautobot",
        "device_filter": {},
    }
```

The backend exposes this via `GET /api/workflow-steps/{plugin_id}/get-config`.
If `config.py` does not exist the endpoint returns `{"plugin_id": "...", "config": {}}`.
The frontend uses this to pre-populate a step's `ConfigPanel` with initial values
and includes the resulting config when saving a workflow to the database.

---

The component must be registered in `frontend/src/lib/plugin-ui-registry.ts`:

```typescript
const PLUGIN_UI_REGISTRY: Record<string, PluginUIComponent> = {
  "device-selection": DeviceSelectionPlugin,
  // add new steps here
};
```
