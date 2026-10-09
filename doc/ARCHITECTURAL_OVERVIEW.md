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

A concrete example: `get-pyats-running-config` and `get-pyats-snapshot`
(`backend/workflow_steps/get_pyats_running_config/executor.py`,
`get_pyats_snapshot/executor.py`) originally looped over `context.devices`
and made one HTTP call to the pyATS shim per device. They were later changed
to group devices by `pyats_source_id` and make one shim call per chunk of up
to 5 devices instead (`backend/workflow_steps/common/pyats_batch.py`; full
rationale in `doc/PYATS_INTEGRATION.md` → "Get & Parse Config"). Both before
and after that change, `StepRunner` still called each step's `execute()`
exactly once per node, with the same full `context.devices` dict — only the
loop *inside* the executor changed.

### Two exceptions to "one node at a time": fan-out and branch concurrency

Under `fan_out.enabled: true` (`doc/WORKFLOW-STEPS.md` → "Fan-out
execution"), each device or chunk runs as its own independent Hatchet child
workflow. Inside that child branch, every step's `execute()` is still called
exactly once per node — but now once **per child**, each with its own
disjoint subset of `context.devices` (one device in `per_device` mode, one
chunk in `chunked` mode), not once for the parent's whole device set. The
"once per node" rule still holds; fan-out just means there are now multiple
parallel node-executions, each scoped to fewer devices.

Separately — and this does not require fan-out at all — two canvas nodes
with no dependency edge between them run **concurrently**, not sequentially.
See "Branch-level concurrency" below for the full mechanics; the short
version is that `execute()` is still called exactly once per node either
way, just not necessarily one-after-another in canvas order anymore.

---

## Branch-level concurrency: independent nodes run in the same wave

**Question:** If the canvas has two branches with no dependency on each
other — `a → {b1, b2} → c` — do `b1` and `b2` run one after the other, or at
the same time? And if they do run concurrently, what stops them from
corrupting shared state (the run's own DB rows, a shared git repository)?

**Answer:** They run concurrently, in every execution path (a plain run, a
post-fan-in resume, and inside one fan-out child's own subgraph) — this is
not opt-in and has no canvas toggle, unlike `fan_out.enabled`. Two
serialisation mechanisms make that safe: one for the run's own bookkeeping,
one for git.

### How the scheduling works

`StepRunner` groups the topologically-sorted canvas into dependency layers —
`services/execution/graph.py::topological_generations` — instead of walking
one flat list. Every node in a layer has all its parents in strictly earlier
layers, so nodes within one layer never depend on each other by
construction. `execute_all` (phase 1), `resume_after_join` (phase 4), and
`subgraph.run_subgraph` (fan-out children) all walk layer by layer; within a
layer, `StepRunner._run_wave` runs every node's `execute()` concurrently via
`asyncio.gather(..., return_exceptions=True)`, and the walk only advances to
the next layer once the whole current one finishes. `c` above only starts
once both `b1` and `b2` are done — not through any wait/join primitive, just
because it isn't "ready" (all parents finished) until then.

A hard, unexpected exception in one sibling (not a step-level failure — those
are already caught and turned into a failed `WorkflowStepResult`, same as
before) doesn't strand or cancel the others in that layer; they finish, then
the exception is re-raised, matching the pre-concurrency contract that such
an exception aborts the whole run — just after the layer completes instead
of immediately.

### The run's own Session

All of this happens inside one `StepRunner` instance sharing one SQLAlchemy
`Session`, which is not safe for interleaved concurrent use. Rather than
give each concurrent branch its own `Session` (the fan-out-child pattern),
`StepRunner` holds a single `asyncio.Lock` (`self._db_lock`) and every
`WorkflowStepResult` write goes through `_persist_step_result`, which
acquires it. This works because `RunRepository.update_step_result`/
`create_step_result` already call `self.db.commit()` internally — each write
is already a self-contained unit, so the lock only needs to stop two
commits interleaving, never the surrounding step work (SSH sessions, HTTP
calls) that's the actual reason to run branches concurrently in the first
place.

### Git working trees

A workflow step (`git-clone`/`git-pull`/`git-push`, `store-artifact` with
`destination: git`, `open-change-request`) that touches a `GitRepository`'s
on-disk working tree is a different hazard: two concurrent callers against
the *same* repository — two sibling branches, or a fan-out child on another
Hatchet worker entirely (a different process, so `StepRunner`'s in-process
`_db_lock` can't help there) — can race on `index.lock` or a non-fast-forward
push. `services/git/repo_lock.py` closes this with a Redis `SET NX EX`
advisory lock keyed by `git_repository_id`. It is fail-soft only when there
is no usable cache (Redis not configured, or erroring while acquiring: the lock
is skipped with a warning). A lock that stays held by another caller past the
90 s acquire timeout **fails the step** (`RuntimeError`) rather than proceeding
on a shared working tree. It does not turn N concurrent callers into one
logical operation, only into N safely-serialised ones — see `doc/WORKFLOW-STEPS.md` → "Writing
concurrency-safe steps" for the author-facing guidance on why a git-touching
step still usually belongs after a join point.

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
`backend/workflow_steps/run_command/exec_mode.py`) loop/gather over
`context.devices` and call a per-device helper (`_run_on_device(device_id,
device, ...)`) that returns an **updated copy**:

```python
failed = device.model_copy(update=update)
return device_id, failed, False
```

Results are reassembled into a new `devices` dict afterward. One device's
failure or update can't leak into another device's copy, because each
`DeviceContext` is an independently produced, immutable Pydantic model.

This same discipline is also what makes concurrent sibling branches safe (see
"Branch-level concurrency" below): two nodes with no dependency edge share
the identical `WorkflowContext` object as their input (no defensive copy is
made), so their concurrent execution only stays correct because neither
mutates it — every step is expected to produce new copies via
`.model_copy(...)`, never write into `context.devices`/`.metadata`/a
`DeviceContext`'s fields in place.

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
- `cancel_run` and Wait & Run batch approval are already workflow-name-agnostic
  (keyed by opaque Hatchet run id or by `hatchet.event.push` event scope) —
  publishing a workflow doesn't change how either behaves.
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

## Nautobot device caching: what is cached, when it is refreshed

**Question:** The Redis page shows "Cached items: 1" — is every device cached
separately, and how does a device added in Nautobot reach a workflow run?

**Answer:** The devices of a Nautobot source are cached in a few Redis **hashes**
(one data hash plus one small index per attribute), and a few other entries are
derived from them. "Cached items" counts Redis keys, not devices.

| Redis key (under `manus-cache:`) | Holds | Written by | TTL |
|---|---|---|---|
| `nautobot:devices:data:<scope>` | hash: device id → JSON of that device | `RefreshNautobotDeviceCache` cron (every 5 min) | `device_ttl_seconds` (default 30 min) |
| `nautobot:devices:idx:<scope>:<field>` (`role`, `status`, `device_type`, `manufacturer`, `platform`) | hash: attribute value → JSON list of device ids | same cron run, swapped in atomically with the data hash | `device_ttl_seconds` |
| `nautobot:devices:location:<scope>:<eq\|not>:<location>` | devices of one location filter (equals / not equals), child locations included | first query of that filter | `location_ttl_seconds` (default 10 min) |
| `nautobot:device_details:<scope>:<id>`, `nautobot:device_attributes:<scope>:<id>:<groups>` | one device's full details / attribute bag | first per-device lookup | `device_ttl_seconds` |

`<scope>` is a hash of the Nautobot URL and token, so several sources never
share entries.

- **Indexed filters** (role, status, device type, manufacturer, platform —
  equals / not equals) read the id list from the index and fetch only those
  devices (`HMGET`), so `role = server` on a few thousand devices only
  deserialises the servers. If the cache is cold or an index is missing they fall
  back to the full list.
- **AND narrowing:** in an AND, the indexed conditions are resolved to device ids
  straight from the indexes and intersected; only the survivors are fetched, and
  the AND's other conditions (name, tag, custom field, nested groups) run over
  just those devices. `role = server AND status = Active` therefore parses the
  servers, not the fleet. OR / NOT groups are not narrowed.
- **Other filters** (name, tag, has-primary, custom field) load the whole data
  hash (`HVALS`) and filter in Python; `!=` on an indexed field does too (its
  result is most of the fleet).
- A filter is several Redis commands, so a cron swap can land between them. The
  fetched devices are therefore checked against the condition that selected them;
  a missing id, a body that no longer matches, a Redis error or corrupt index
  entry all discard the indexed read and fall back to the full list (one
  snapshot) — never to an empty or partial answer.
- The cron rewrites the data hash and all indexes in one `MULTI/EXEC` (build under
  a temp key, `RENAME` over the live key), so a reader never sees a mix of old
  and new. The read log lines (`Cache index ...`, `Cache fetch ...`,
  `Cache hit ...`) show Redis vs. parse time in ms, handy for comparing timings.
- **Location** can't use the cached devices: Nautobot resolves the
  child-location hierarchy server-side, and the cached devices only carry their
  own location name. It queries Nautobot, and caches each distinct filter's result. Locations are
  matched exactly — the operators are **equals** and **not equals** only, never
  "contains" ("City" must not match "City A"); the API rejects a location
  `contains`/`not_contains` condition and the UI doesn't offer it. Device names
  and custom fields keep their "contains" operator. Empty and
  errored results are never cached, so a just-created location shows up at once.
  IP-prefix and primary-prefix filters always query Nautobot live.
- **Freshness:** each cron run compares the fresh device list with the stored
  one and, if anything differs (device added, removed, moved, or a detail such
  as its primary IP edited), drops all location entries of that source. A change
  therefore reaches inventories and runs within about 5 minutes; the TTL is only
  an upper bound if the cron isn't running.
- **Rebuild cache** (Settings → Redis → Cache Management, `POST /cache/rebuild`)
  starts the on-demand `RebuildNautobotDeviceCache` Hatchet workflow: the same
  routine as the cron, but forced — it reloads every device from Nautobot and
  drops the location, details and attributes entries even if nothing changed.
  The location filters that were cached at that moment are then re-run (5 at a
  time; a failing one is just left uncached), so the ones people actually use are
  warm again; details/attributes and never-used filters refill on first use.
  Nothing is dropped if Nautobot can't be reached. Unlike **Clear cache** it
  never empties the cache first, so runs during a rebuild still hit warm data.
  It needs the worker running; the request itself returns immediately.

Code: `services/sources/nautobot/query_service.py` (`refresh_bulk_cache`, the
index reads), `evaluator.py` (`_narrow_by_index`), `services/cache/redis_cache_service.py`
(hash helpers, `replace_hashes`), `live_query_mixin.py` (location cache),
`services/nautobot/devices/query.py` (`invalidate_cache`),
`hatchet/workflows/cache_devices.py`.

## Device selection: three representations of "which devices"

**Question:** A saved inventory, a `get-nautobot-devices` canvas node, and an
actual Nautobot query each seem to describe device selection differently. Are
these the same format, and if not, what converts between them?

**Answer:** No — there are three genuinely different shapes. Getting this
wrong (assuming a converter exists where it doesn't, or that two of these
shapes are interchangeable) is an easy mistake — a real one, corrected in
`doc/ai_collaboration/PROCESS.md`'s 2026-09-24 updates.

1. **Saved format** — `Inventory.conditions` (`core/models/inventories.py`), a
   JSON string decoded by `InventoryService`/`_model_to_dict`
   (`services/sources/nautobot/persistence_service.py`) to
   `[{"version": 2, "tree": {"type": "root", "internalLogic": "AND"|"OR",
   "items": [...]}}]`. This is what a saved inventory actually stores in the
   database.
2. **Canvas format** — `device_filter` on a `get-nautobot-devices` node's
   `pluginConfig`: `{"id": "root", "logic": "AND"|"OR", "negate": bool,
   "items": [...]}`. An *ad-hoc* filter stored in the step itself — only used
   by a step that has **no** saved inventory selected (imported or AI-written
   workflows; the builder UI no longer creates these).
3. **Runtime query format** — `LogicalOperation`/`LogicalCondition`
   (`models/sources_nautobot.py`), what actually gets sent to Nautobot.

**How a `get-nautobot-devices` step finds its devices** (executor:
`workflow_steps/get_nautobot_devices/executor.py`). The API process and the
Hatchet worker share every stage after the first decision, because both build
the device list with `service_factory.build_nautobot_source_service` and
`NautobotSourceService.preview_inventory`:

- **The step names a saved inventory** — either `inventory_id` selected in the
  builder (`inventory_source: "fixed"`) or the id held in a run parameter
  (`"run_param"`). Both go through one helper,
  `NautobotSourceService.resolve_saved_inventory_devices_by_id`, which loads
  the inventory **at run time**, RBAC-checked against the user that triggered
  the run, and converts it with `utils/inventory_converter.py::
  convert_saved_inventory_to_operations`. Editing the saved inventory therefore
  changes what the next run targets. The builder only stores the *link*
  (`inventory_id` + `inventory_name` for display); selecting an inventory does
  not copy its filter or device list into the step, and any copy left in the
  step by older versions is ignored. A deleted, inactive or inaccessible
  inventory fails the step with a message naming it — it never silently falls
  back to an old copy.
- **The step names no inventory** — the ad-hoc `device_filter`
  (`_filter_tree_to_operations`, canvas → runtime) or `device_ids`
  (`resolve_devices_by_ids`) stored in the step is the definition.
- **Previewing in the builder** ("Preview devices") calls
  `GET /sources/nautobot/{inventory_id}/devices` for a linked inventory — the same
  resolution a run performs — and the `/preview` / `/preview-device-ids`
  endpoints only for an ad-hoc selection.

Conversions between shapes: **saved → runtime** is
`convert_saved_inventory_to_operations` (above); **canvas → runtime** is
`_filter_tree_to_operations` (ad-hoc steps only). **Saved → canvas** exists only
for authoring (`savedConditionsToFilterTree` in the frontend, and its Python
port `backend/scripts/ai_inventory_filter.py::saved_conditions_to_device_filter`)
and is no longer part of selecting an inventory.

**Why live and not a snapshot:** an earlier design froze the inventory's filter
into the step when it was selected, so editing the inventory later silently did
not affect existing steps — runs kept using devices nobody had chosen any more.
The step now behaves like any other reference: it points at the inventory, and
the inventory is the single source of truth. The cost is that a workflow
definition is no longer self-contained: it depends on the inventory still
existing and being visible to whoever runs it.

---

## Canvas groups: a view over the flat graph, not an execution unit

**Question:** Does putting steps into a group (or a "Step Group") change how the
workflow runs?

**Answer:** No. A group is frontend-only organisation. `canvas_nodes` and
`canvas_edges` always hold the complete flat graph, and `StepRunner` executes
that graph exactly as if no groups existed — same layers, same concurrency, same
per-node results. `canvas_groups` only records *membership* (which node ids belong
to which group); a group's input/output ports are derived from the edges that
cross its boundary in the browser and are never persisted. (A group may also record
the background it sits on — `CanvasGroup.parentId` — purely so it moves with that
background; it has no effect on execution.) The one backend touch
is `WorkflowService._repair_orphan_groups`, which drops dangling member ids on
save and dissolves selection groups left with fewer than two members (palette
"Step Group" containers are exempt). Full design:
[`doc/FEATURE-GROUPING.md`](./FEATURE-GROUPING.md).

---

## Change requests: a review gate as two decoupled runs

A config change that must be reviewed before it reaches devices is **not** a
paused workflow — the `execute_steps` durable task is capped at 24 h, and a
review can take days. Instead the pipeline is two ordinary `WorkflowRun`s
joined by a `change_requests` row:

1. A **stage run** ends in the `open-change-request` step, which renders the
   configs, pushes them to a per-change git branch, stores a diff, and writes
   the `ChangeRequest` in `status="staged"`. The run then finishes normally —
   the "wait" is just that row.
2. Approval — a JWT `POST /change-requests/{id}/approve` **or** a signed inbound
   git webhook (`POST /webhooks/git/{repo_id}`, the one unauthenticated,
   non-proxy entry point, guarded by HMAC + its own per-repo+IP rate limit (60/min) + replay dedup +
   fail-closed) — atomically transitions the row and dispatches a **deploy
   run** through the same `resolve_dispatch_workflow(...).run_no_wait(...)` path
   a schedule uses. `WorkflowRun.change_request_id` links the deploy run back;
   `git-clone`/`git-pull` with `use_change_request_branch: true` then operate on
   the change request's branch. Every state move is a conditional
   `UPDATE ... WHERE status IN (...)`, so a UI click racing a webhook yields
   exactly one deploy run.

Full spec: [`doc/CICD_PIPELINE.md`](./CICD_PIPELINE.md).

---

## Secret redaction: sealed envelopes plus run-scoped content scrubbing

Secrets that ride in `DeviceContext.attribute_bags` are sealed (Fernet envelopes) and persisted only as
`***REDACTED***` (`redact_secrets_in_data`). Because a step may unwrap a secret and copy it into free
text (a command echo, a diff line, an error message), every `StepRunner` entry point that holds a run
segment open (`execute_all`, `resume_after_join`, `execute_subgraph`, and the fan-out child task) runs
inside `run_secret_scope()`: `unwrap_secret` and the credential decrypt methods register each cleartext
(8+ characters) in a per-segment registry, and `redact_secrets_in_data` / `scrub_known_secrets` replace
exact occurrences in string leaves, overlap-safe. A fan-out child scrubs its result before returning it
to the parent, so the parent's persisted output and the Hatchet result carry no cleartext either. A
secret that never passed through those calls (typed into a template) is unknown to the redactor. See
`doc/WORKFLOW-STEPS.md`.

## Per-user rate limiting

Expensive endpoints (Netmiko, git sync, template render, ISE ops, Nautobot analyze, Secret Manager
test, Batfish queries) carry `Depends(rate_limited("<bucket>", attempts=…, window_seconds=…))`
(`core/rate_limit.py`): a sliding window per authenticated user and bucket, counted and recorded
atomically (Redis Lua script), 429 with `Retry-After` when exceeded. Unlike login, a Redis outage falls
back to an in-process window instead of blocking operators. A bucket name is one budget; reusing it with
another fails at import.
