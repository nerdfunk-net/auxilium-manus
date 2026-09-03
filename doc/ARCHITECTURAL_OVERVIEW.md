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

> **Many schedules per workflow, each parameterized.** A workflow is no longer
> limited to one schedule. `workflow_schedules.workflow_id` is a plain indexed
> FK (not `UNIQUE`), each row carries its own `name` and `run_inputs` (a
> per-schedule static-attribute value bag), and schedules are managed from the
> dedicated **Schedules** app (`/schedules`), not the workflow builder's
> properties panel. See `doc/SCHEDULES.md`. The mechanics below are otherwise
> unchanged.

### 1. Saving a schedule registers it with Hatchet immediately

`ScheduleService.create_schedule` / `update_schedule`
(`backend/services/execution/schedule_service.py`) registers the schedule
directly with Hatchet at save time:

```python
if schedule.schedule_type == "cron":
    result = hatchet.cron.create(
        workflow_name="ScheduledWorkflowTrigger",
        cron_name=f"workflow-{schedule.workflow_id}-schedule-{schedule.id}",
        expression=schedule.cron_expression,
        input={"workflow_id": schedule.workflow_id, "schedule_id": schedule.id},
        additional_metadata={"workflow_id": schedule.workflow_id},
    )
else:
    result = hatchet.scheduled.create(
        workflow_name="ScheduledWorkflowTrigger",
        trigger_at=schedule.run_at,
        input={"workflow_id": schedule.workflow_id, "schedule_id": schedule.id},
        additional_metadata={"workflow_id": schedule.workflow_id},
    )
```

Both paths target a fixed wrapper workflow, `ScheduledWorkflowTrigger`, with a
small, fixed payload (`workflow_id`, `schedule_id` — not the workflow
definition or the `run_inputs` themselves). The `cron_name` is keyed on the
**schedule** id, not just the workflow, so a workflow's multiple schedules
don't collide. The returned Hatchet cron/scheduled ID is persisted on the
`WorkflowSchedule` row (`hatchet_cron_id` / `hatchet_scheduled_id`) so it can
be deleted or replaced later (`_delete_hatchet_entry`).

Creating a schedule also **publishes the workflow to the background tier**
(`BackgroundTierService.publish`, concurrency limit from the dialog, default
`1`) so overlapping fires of the same workflow are serialised by Hatchet
rather than each opening its own device fan-out — see "Background-tier
workflows" below. This is why `POST /api/schedules` requires
`workflows:publish`.

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
4. Resolves `run_inputs` by merging the **schedule's own `run_inputs`** with
   the workflow's declared static-attribute defaults
   (`services/execution/run_input_validation.py::resolve_run_inputs`), then
   re-checks every `type: "reference"` value still resolves for the schedule
   owner (`services/execution/reference_resolver.py::validate_reference_inputs`
   — inventory not deleted, credential not rotated away). A required attribute
   still missing, or a reference that no longer resolves, fails the run
   immediately (`status="failed"`, `error_category="configuration"`) rather
   than dispatching with an incomplete/broken input bag. `triggered_by_id` is
   the schedule's `created_by_id`, so credential/inventory resolution is scoped
   to that user.
5. Dispatches into the execution engine exactly like a manual "Run" click
   would, via the same resolver both paths share:
   `resolve_dispatch_workflow(workflow, db).run_no_wait(WorkflowRunInput(run_id=run.id))`
   (`hatchet/workflows/dispatch.py`) — see "Background-tier workflows" below
   for what that resolver actually picks.

### Summary

- The schedule lives in Hatchet's own scheduler from the moment it's saved —
  not in application memory, not tied to a browser session.
- For a workflow on the default (unpublished) tier, only two things need to
  be up for a scheduled run to actually execute: the **Hatchet worker
  process** (`hatchet/worker.py`) and **PostgreSQL**. The API process and
  frontend can be down. A workflow published to the background tier
  additionally needs the **dynamic worker process** (`hatchet/dynamic_worker.py`)
  up — see "Background-tier workflows" below.
- A **required static attribute with no default** must be supplied by the
  schedule's own `run_inputs` (the Schedules app validates this at save time).
  A schedule that doesn't cover it — or a manual-trigger workflow with no
  schedule — still fails such a run immediately with a configuration error.

---

## Background-tier workflows: per-workflow Hatchet identity

**Question:** Every workflow dispatches through one shared Hatchet workflow,
`"WorkflowExecution"` — so how can I get Hatchet's own per-workflow
concurrency limit (e.g. "never run two overlapping instances of this specific
workflow") when Hatchet only sees one workflow type across the whole app?

**Answer:** A workflow can be **published** to a second, opt-in tier that
gives it its own dedicated Hatchet workflow name, registered on a **second,
separate worker process** — without changing anything about the default,
unpublished path.

### The two tiers

- **Default (unpublished):** every workflow starts here. Dispatch always
  targets the single static `"WorkflowExecution"` workflow
  (`hatchet/workflows/workflow_run.py`), run by `hatchet/worker.py`. Zero
  friction — create, edit, and run a workflow with no extra step, exactly as
  before this feature existed.
- **Published (background tier):** an admin (`workflows:publish` permission)
  toggles "Publish to background tier" in the workflow's Properties panel,
  optionally setting a concurrency limit. This writes one row to
  `workflow_background_tier` (`core/models/background_tier.py`) — existence
  of the row *is* the published flag — assigning the workflow a permanent,
  deterministic name, `f"WorkflowBackground-{workflow_id}"`, keyed on the
  workflow's own database ID — deliberately not its display name, which has
  no uniqueness guarantee in this app (`repositories/workflow_repository.py::name_exists`
  only enforces uniqueness within `(name, folder, creator_id/visibility)`,
  and only as a soft check at save time, not a database constraint).

### Dispatch resolution

Both dispatch call sites — `RunService.trigger_run` (manual "Run") and
`scheduled_trigger.py`'s `dispatch` task (scheduled/cron) — resolve the
target through one shared helper, `resolve_dispatch_workflow(workflow, db)`
(`hatchet/workflows/dispatch.py`): unpublished → the existing
`workflow_execution` object; published → a lightweight client handle built
from `hatchet_workflow_name`. Both paths call `.run_no_wait()` on whichever
object comes back — a run doesn't know or care which tier it's on beyond that
one lookup.

### The second worker

A dedicated worker process, `hatchet/dynamic_worker.py`, registers one
Hatchet workflow per published row at startup — each attaching the *same*
`prepare`/`execute_steps` task functions `WorkflowExecution` uses (via a
shared `build_workflow_execution()` factory), just under a different name and
optional `concurrency=` limit. It also registers `DeviceGroupExecution`
alongside them, so fan-out from a published workflow still works.

Because Hatchet's worker action registration is fixed for a process's
lifetime, a newly published/edited/unpublished workflow only becomes
dispatchable once this process restarts. It handles that itself.

It logs to its own sink, `worker-background.log` (process name
`worker-background` in `core/logging_config.py`), rather than sharing the live
worker's `worker.log` — two processes must never write the same
`RotatingFileHandler` file. Settings → Logging lists both worker files, and the
persisted overrides are re-applied per process on each worker's startup.

### How the restart is triggered — no Redis, no pub/sub, no event

Publishing (or unpublishing, or editing a concurrency limit) writes **only** a
row to `workflow_background_tier` — `BackgroundTierService.publish` /
`BackgroundTierRepository.publish` (`services/execution/background_tier_service.py`,
`repositories/background_tier_repository.py`). Nothing is sent to Redis,
Hatchet, or any other process at that moment; the API request just commits
and returns.

The dynamic worker independently polls that same table for a change — it is
the one doing the watching, not the one being notified:

```python
# hatchet/dynamic_worker.py::_self_restart_on_change
while True:
    await asyncio.sleep(poll_interval_seconds)   # HATCHET_DYNAMIC_WORKER_POLL_INTERVAL_SECONDS, default 30s
    with SessionLocal() as db:
        fingerprint = BackgroundTierRepository(db).fingerprint()
    if fingerprint != initial_fingerprint:
        os.kill(os.getpid(), signal.SIGTERM)
        return
```

`fingerprint()` is one cheap aggregate — `SELECT COUNT(*), MAX(updated_at)
FROM workflow_background_tier` — captured once at the worker's own startup
and re-checked on every tick; a publish, unpublish, or edited concurrency
limit always changes the count or `updated_at`, so one query catches all
three cases. On a mismatch the process sends itself `SIGTERM` — the same
signal a normal supervised stop already uses, so it exercises Hatchet's
existing graceful-shutdown path (drains in-flight slots, respects
`stopwaitsecs=600` under supervisord) rather than a new one — then exits;
`main()` re-runs `_load_published_workflows()` from scratch on the next
start, so the new process doesn't need to know *what* changed, only *that*
something did.

Postgres was chosen deliberately over adding a Redis pub/sub channel or an
event: it's already the source of truth for `workflow_background_tier`, so
polling it directly means there's nothing to keep in sync and no delivery
guarantee to worry about (a missed pub/sub message would mean a publish
silently never takes effect; a missed poll tick just gets caught by the next
one). The cost is a bounded propagation delay — up to one poll interval
between publishing and the workflow becoming dispatchable — which the
Properties panel's "Publish" UI states explicitly.

In production the restart is brought back up by `supervisord`'s
`autorestart=true` in its own container, `manus-background-worker`
(`docker/supervisord-background-worker.conf` → `[program:hatchet-dynamic-worker]`)
— a separate container from the live worker's `manus-worker`
(`docker/supervisord-worker.conf`), so a self-restart to pick up a
publish/unpublish/edit never touches a live/interactive run on the other
container; in local dev, `scripts/run_dynamic_worker_dev.py` does the same
(it does not use `watchfiles.run_process` for this, since that utility only
reacts to file changes, not the process exiting on its own — the script
wraps the process directly and respawns it on any exit).

### What this does *not* change

- Fan-out per-device concurrency (`fan_out.max_concurrency`) is untouched —
  a background-tier concurrency limit governs *top-level runs* of one
  workflow, not devices within a run.
- `cancel_run`, the debug-mode step gate, and Wait & Run batch approval are
  all already workflow-name-agnostic (keyed by opaque Hatchet run id or by
  `hatchet.event.push` event scope) — publishing a workflow doesn't change
  how any of those behave.
- Cron/scheduled trigger *registration* (`hatchet.cron.create`/`hatchet.scheduled.create`
  against the fixed `"ScheduledWorkflowTrigger"` workflow, described above)
  is unaffected — only what `"ScheduledWorkflowTrigger"`'s `dispatch` task
  does with the run once it fires changes.

---

## Version-controlled workflows: Git is a mirror, not a source of truth

**Question:** When a workflow has version control turned on, does its JSON
move into Git and out of the database? If a run executes while the two
disagree, which one wins — and what happens to a save if Git is
unreachable?

**Answer:** PostgreSQL is unconditionally the full, authoritative store for
every workflow. Git — when enabled — is an additional, best-effort mirror
written *after* the database save already succeeded, purely for history,
diffing, and rollback. Turning version control on never moves data out of
the database, and a Git failure never blocks or rolls back a save.

### The database always holds the complete definition

The `workflows` table's `canvas_nodes`, `canvas_edges`, `canvas_groups`, and
`static_attributes` columns hold the full workflow graph for *every*
workflow — version-controlled or not. `is_version_controlled`
(`core/models/workflows.py`) is just a boolean opt-in flag on that same row;
flipping it off doesn't delete or move anything, it only stops the mirroring
described below. A triggered run always reads this live database row at
execution time (`StepRunner`/`load_execution_graph`) — there is no
run-to-git-commit pinning. This was a deliberate scope decision: Git exists
for a human to browse/diff/roll back, not to make runs reproducible against
a specific commit, so the execution path is completely unchanged by whether
a workflow is version-controlled.

### What gets mirrored, and when

`WorkflowGitService.sync_workflow_to_git`
(`backend/services/workflow/workflow_git_service.py`) runs at the end of
`WorkflowService.create_workflow` / `update_workflow`
(`backend/services/workflow/workflow_service.py`) — strictly *after* the
database transaction has already committed. If the workflow is
version-controlled and a repository is configured, it serializes the same
content that's in the database (minus DB-only bookkeeping like `id` and
timestamps) to pretty-printed JSON, writes it to `workflows/<uuid>.json` in
the repo's working tree, then commits and pushes. There is exactly one
global repository for all version-controlled workflows — enforced as the
single `GitRepository` row with `category="workflows"`, configured once
under Settings → Git Repositories — not a per-workflow repo choice.

### Best-effort, not transactional

`sync_workflow_to_git` never raises. On any failure (repo unreachable, auth
failure, nothing configured, workflow not version-controlled) it returns a
`status` of `"failed"` or `"skipped"` instead, which rides back to the
frontend as a `git_sync` field on the save response — surfaced as a
non-blocking toast, never a rolled-back save. A workflow that isn't
version-controlled short-circuits before any Git or even repository-lookup
call, so the common case (most workflows) pays no cost for this feature
existing.

### Restore is forward-only

Restoring an older commit (`WorkflowGitService.restore_version` →
`WorkflowService.restore_workflow_version`) reads that commit's JSON and
applies it through the exact same `update_workflow` path a normal save
uses — full validation, then a *new* mirrored commit. Restore never runs
`git reset`/`git revert`/history rewrite, so Git history only ever grows
forward, and a "bad" restore is itself just one more commit to restore away
from.
