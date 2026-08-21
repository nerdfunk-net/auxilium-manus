# Architectural Overview

Deep-dive notes on how specific parts of the system behave, aimed at answering
"how does this actually work" questions that aren't obvious from the code
layout alone. Complements `doc/WORKFLOW-STEPS.md` (step contracts, registry,
fan-out) and `doc/MANUS_BASIS_DATATYPE.md` (the canonical `WorkflowContext`/
`DeviceContext` shape, capability model, merge rules) rather than repeating
them — this file references those docs instead of duplicating them.

More topics will be added here over time.

---

## Step execution granularity: once per node, not once per device

**Question:** When a workflow step runs against many devices, does the engine
call that step's code once per device, or once for the whole batch? If I add
a new step, do I need to worry about it being invoked repeatedly per device?

**Answer:** Once per node, per run. A step's `execute()` (the contract is
documented in full in `doc/WORKFLOW-STEPS.md` → "executor.py — required for
every executable step") is called **exactly once** by `StepRunner`
(`backend/services/execution/step_runner.py`) each time execution reaches
that node — never once per device. It receives the **entire** current device
set in a single `context: WorkflowContext` argument, where
`WorkflowContext.devices` is a `dict[str, DeviceContext]` holding every
device that reached this node from upstream (canonical shape defined in
`doc/MANUS_BASIS_DATATYPE.md`; see "Per-device data isolation" below for the
isolation guarantees). There is no per-device invocation of `execute()`
anywhere in the engine — `doc/WORKFLOW-STEPS.md`'s "Execution path" diagram
(`StepRunner.execute_all() → STEP_REGISTRY[step_type] → execute()`) is the
whole call chain, and it runs once per node.

### What a step does with that dict is entirely up to the step

Since `execute()` gets the whole `context.devices` dict at once, how it
processes those devices — sequentially, concurrently via `asyncio.gather`,
one external call per device, or several devices batched into one external
call — is a private implementation choice inside that step, invisible to the
engine and to every other step. Nothing about `StepRunner`, the registry, or
the canvas/config changes based on that choice.

A concrete example: `get-pyats-config` and `get-pyats-snapshot`
(`backend/workflow_steps/get_pyats_config/executor.py`,
`get_pyats_snapshot/executor.py`) originally looped over `context.devices`
and made one HTTP call to the pyATS shim per device. They were later changed
to group devices by `pyats_source_id` and make one shim call per chunk of up
to 5 devices instead (`backend/workflow_steps/common/pyats_batch.py`; full
rationale in `doc/PYATS_INTEGRATION.md` → "Get & Parse Config"). Both before
and after that change, `StepRunner` still called each step's `execute()`
exactly once per node, with the same full `context.devices` dict — only the
loop *inside* the executor changed.

### The one exception: fan-out

Under `fan_out.enabled: true` (`doc/WORKFLOW-STEPS.md` → "Fan-out
execution"), each device or chunk runs as its own independent Hatchet child
workflow. Inside that child branch, every step's `execute()` is still called
exactly once per node — but now once **per child**, each with its own
disjoint subset of `context.devices` (one device in `per_device` mode, one
chunk in `chunked` mode), not once for the parent's whole device set. The
"once per node" rule still holds; fan-out just means there are now multiple
parallel node-executions, each scoped to fewer devices.

---

## Per-device data isolation

**Question:** When a workflow runs against multiple devices, how can we be
sure the app treats each device separately and never mixes their data? Can a
device "see" the attribute bag of another device?

**Answer:** Isolation is structural, not just conventional — the data model
and the resolver APIs make cross-device reads impossible by construction.

### The data model

Every device's state lives in its own `DeviceContext` object
(`backend/models/workflow_context.py`):

```python
class DeviceContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    hostname: str
    ...
    attribute_bags: dict[str, dict[str, Any]] = Field(default_factory=dict)
    parsed: dict[str, Any] = Field(default_factory=dict)
    command_results: dict[str, list[CommandResult]] = Field(default_factory=dict)
    status: DeviceStatus = DeviceStatus.PENDING
    errors: list[DeviceError] = Field(default_factory=list)
```

A `WorkflowContext` — the single envelope that flows along every edge of the
workflow graph — just holds a `dict[str, DeviceContext]` keyed by device ID:

```python
class WorkflowContext(BaseModel):
    devices: dict[str, DeviceContext] = Field(default_factory=dict)
    pending_commands: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

There is no shared/global attribute bag that all devices write into. Each
device's `attribute_bags` is its own dict instance.

### No cross-device read path exists

The functions that resolve attribute values only ever take a **single**
`DeviceContext` as input:

- `resolve_device_attribute(device, path)` / `resolve_device_value(device, path)`
  (`backend/services/workflow_context/attribute_path.py`) — resolves a dotted
  path against *that device's* `attribute_bags` / `parsed` / scalar fields
  only.
- `build_jinja_context(device, ...)` (`backend/workflow_steps/common/jinja_render.py`)
  — same pattern; builds the Jinja namespace from one device.

Neither function receives the rest of `WorkflowContext.devices`, so a Jinja
template or a `route-on-attribute` condition evaluated "for device A" has no
syntax that can address device B's data — the resolver simply never receives
it.

### Per-device processing is immutable, not shared-mutable

Steps that operate on multiple devices (e.g. `run-command`,
`backend/workflow_steps/run_command/executor.py`) loop/gather over
`context.devices` and call a per-device helper (`_run_on_device(device_id,
device, ...)`) that returns an **updated copy**:

```python
failed = device.model_copy(update=update)
return device_id, failed, False
```

Results are reassembled into a new `devices` dict afterward. One device's
failure or update can't leak into another device's copy, because each
`DeviceContext` is an independently produced, immutable Pydantic model.

SSH sessions follow the same per-device discipline: `DeviceSessionPool`
(`backend/services/network/netmiko/session_pool.py`) keys pooled connections
by `(host, device_type, credential_reference)`, so a session is never shared
across devices.

### Fan-out strengthens isolation further

When an inventory step has `fan_out.enabled: true` (see
`doc/WORKFLOW-STEPS.md` → "Fan-out execution"), each device or chunk runs as
an **independent Hatchet child workflow**, each with its own disjoint subset
of `context.devices` — physical process-level separation, not just logical
separation within one context. `merge_fan_out_contexts`
(`backend/services/workflow_context/merge.py`) performs a plain union of
devices when folding children back together; it never merges two children's
data for the same device, since fan-out children own disjoint device sets by
construction.

**Caveat:** this guarantee is about *device* data. Workflow-level
`WorkflowContext.metadata` (not `attribute_bags`) merges with
**first-child-wins** semantics on conflict under fan-out — so a step that
writes an aggregate value into `metadata` expecting a per-run total will not
get that reconstructed correctly across fan-out children. Device data itself
never mixes.

---

## Scheduling: cron and run-once-in-the-future

**Question:** When a workflow is configured with a cron schedule or a
one-time future run, is it registered with Hatchet so it fires without the
workflow ever being opened again?

**Answer:** Yes. Once saved, the schedule is owned entirely by Hatchet's own
server-side scheduler. Neither the frontend/browser nor even the FastAPI API
process needs to be running for it to fire — only PostgreSQL and the Hatchet
**worker** process matter.

### 1. Saving a schedule registers it with Hatchet immediately

`ScheduleService.upsert_schedule` (`backend/services/execution/schedule_service.py`)
registers the schedule directly with Hatchet at save time:

```python
if data.schedule_type == "cron":
    result = hatchet.cron.create(
        workflow_name="ScheduledWorkflowTrigger",
        cron_name=f"workflow-{workflow_id}",
        expression=data.cron_expression,
        input={"workflow_id": workflow_id, "schedule_id": schedule.id},
        additional_metadata={"workflow_id": workflow_id},
    )
else:
    result = hatchet.scheduled.create(
        workflow_name="ScheduledWorkflowTrigger",
        trigger_at=data.run_at,
        input={"workflow_id": workflow_id, "schedule_id": schedule.id},
        additional_metadata={"workflow_id": workflow_id},
    )
```

Both paths target a fixed wrapper workflow, `ScheduledWorkflowTrigger`, with a
small, fixed payload (`workflow_id`, `schedule_id` — not the workflow
definition itself). The returned Hatchet cron/scheduled ID is persisted on
the `WorkflowSchedule` row (`hatchet_cron_id` / `hatchet_scheduled_id`) so it
can be deleted or replaced later (`_delete_hatchet_entry`).

### 2. Firing is owned by Hatchet, independent of the app

When a cron tick or a `run_at` timestamp arrives, Hatchet's engine (its own
DB/queue, external to this app) dispatches `ScheduledWorkflowTrigger` to
whichever **Hatchet worker process** is running — in dev, that's
`python scripts/run_worker_dev.py`. This is a separate process from the
FastAPI API and from the frontend; no browser tab or open workflow editor is
involved at all.

### 3. The wrapper workflow does the actual dispatch

`dispatch()` in `backend/hatchet/workflows/scheduled_trigger.py` runs inside
the worker process when triggered:

1. Re-reads the `WorkflowSchedule` row and skips if it was disabled/deleted
   between the tick firing and this task running (avoids running a stale
   config — cron replays a fixed input payload, it doesn't call back into the
   app to check first).
2. Creates a fresh `WorkflowRun` row (`trigger_type="scheduled"`).
3. Marks the schedule triggered — disabling it if `schedule_type == "once"`
   (a one-time trigger is consumed on fire; a cron keeps repeating).
4. Resolves `run_inputs` from the workflow's declared static-attribute
   *defaults only* (`services/execution/run_input_validation.py::resolve_run_inputs`)
   — there is no operator to prompt for a scheduled run. A required static
   attribute with no default fails the run immediately
   (`status="failed"`, `error_category="configuration"`) rather than
   dispatching with an incomplete input bag.
5. Dispatches into the normal execution engine exactly like a manual "Run"
   click would: `workflow_execution.run_no_wait(WorkflowRunInput(run_id=run.id))`.

### Summary

- The schedule lives in Hatchet's own scheduler from the moment it's saved —
  not in application memory, not tied to a browser session.
- Only two things need to be up for a scheduled run to actually execute: the
  **Hatchet worker process** and **PostgreSQL**. The API process and frontend
  can be down.
- A workflow with a **required static attribute that has no default** is
  effectively manual-trigger-only: every scheduled/cron run for it will fail
  immediately with a configuration error instead of executing, since nothing
  can supply that value unattended.
