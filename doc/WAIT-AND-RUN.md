# Wait & Run — User-Approved Batched Fan-Out Execution

**Status:** Implemented (backend + frontend), per the checklist in §11.
**Scope:** Backend orchestration (Hatchet), run API, run data model, fan-out config UI,
run monitoring UI.

---

## 1. The Problem

A typical high-risk workflow (e.g. rolling out a new TACACS+ key) targets *hundreds* of
devices. No responsible network admin pushes a config change to all of them at once: if
the change is wrong, the blast radius is the entire network. The established operational
practice is **canary batching** — run the change on ~10 devices, verify the result, then
release the next 10, and so on.

Today Auxilium Manus cannot do this:

- The inventory steps (`get-nautobot-devices`, `get-git-devices`, `get-ise-devices`,
  `get-from-list`) always emit the **full** device list.
- Fan-out (`doc/WORKFLOW-STEPS.md` → *Fan-out execution*) can already split devices into
  chunks (`mode: "chunked"`, `chunk_size: 10`), but `_dispatch_children()` in
  `backend/hatchet/workflows/workflow_run.py` dispatches **all** child workflows
  immediately (throttled only by `max_concurrency`). There is no way to stop between
  chunks.
- There is no user-facing gate that says *"batch 1 is done — inspect the results, then
  click to release batch 2"*.

### Desired user flow

1. User designs a workflow: inventory step (fan-out enabled) → get configs → prepare new
   config → push config → (fan-in → git export).
2. User clicks **Run**. The first batch of N devices executes.
3. The run **pauses**. The UI shows: *"Batch 1/10 finished (10 ok, 0 failed). Waiting
   for approval to run batch 2 (devices: r11…r20)."*
4. User inspects step results/artifacts for the finished devices.
5. User clicks **Run next batch** — batch 2 executes — pause — repeat.
   Or clicks **Run all remaining** to finish without further pauses.
   Or clicks **Cancel** to stop the run entirely.

---

## 2. Why NOT a canvas step

The obvious idea — a "Wait & Run" node placed on the canvas — does **not** work with the
execution model:

- A step executor (`workflow_steps/{step}/executor.py`) receives one context and returns
  `StepOutcome`s. Under fan-out, the child branch runs once **per child workflow**
  (`DeviceGroupExecution`), each child seeing only its own device subset. A "wait" step
  inside the child branch would pause every child independently — it cannot sequence
  *which* child runs next, and it cannot see or control the parent's dispatch loop.
- The batching decision ("release the next N devices") is inherently a property of the
  **fan-out dispatch loop** in the parent orchestration
  (`workflow_run.py::_dispatch_children`), not of any node in the graph.

**Decision:** Wait & Run is implemented as an **approval option on the fan-out
configuration** of inventory steps, enforced by the parent Hatchet orchestration between
child-workflow batches. No new canvas step, no registry entry, no executor.

---

## 3. Existing building blocks (reuse, don't reinvent)

The **debug-mode "Next Step" gate** already implements a durable user-driven pause and
is the template for everything below:

| Piece | Where | What it does today |
|---|---|---|
| Durable wait | `backend/hatchet/workflows/workflow_run.py::_run_steps_until_fan_out_or_done` | `await ctx.aio_wait_for_event(event_key, scope=event_key, lookback_window=DEBUG_STEP_EVENT_LOOKBACK)` pauses the durable task until an event arrives. `scope` + `lookback_window` close the race where the user clicks before the wait has registered (see the `DEBUG_STEP_EVENT_LOOKBACK` comment). |
| Pause bookkeeping | `RunRepository.update_run_status` (`backend/repositories/run_repository.py`) | Sets `status="paused"`, `current_node_id`, `debug_message`; clears `current_node_id` on terminal statuses. |
| Resume trigger | `RunService._push_continue_event` (`backend/services/execution/run_service.py`) | `hatchet.event.push(event_key, {}, scope=event_key)`. |
| Resume endpoints | `POST /runs/{id}/step`, `/runs/{id}/continue` (`backend/routers/workflow_runs.py`) | Validate `status == "paused"`, push the event. |
| Frontend buttons | `workflow-topbar.tsx` (`isAwaitingStep` → "Next Step" / "Run to completion") + mutations in `use-workflow-run-mutations.ts` | Poll run status; show buttons while paused. |
| Paused banner | `workflow-executions-panel.tsx::RunRow` | Shows `run.debug_message` in amber while `status === "paused"`. |

Fan-out already supports the batch **shape** the user wants:

- `fan_out: {enabled, mode: "per_device"|"chunked", chunk_size, max_concurrency}` in the
  inventory step's `pluginConfig`, copied into `context.metadata["_fan_out"]` by each
  inventory executor (e.g. `workflow_steps/get_nautobot_devices/executor.py` line ~127).
- `_dispatch_children()` builds `groups: list[list[device_id]]` (one group per device,
  or per chunk) and runs one `DeviceGroupExecution` child per group.
- `_aggregate_and_persist()` merges child outcomes into the parent's
  `WorkflowStepResult` rows; `resume_after_join()` runs post-fan-in nodes once.

---

## 4. Design overview

```
Run click
   │
   ▼
Phase 1 (unchanged): parent runs steps topologically until the inventory
step emits _fan_out.enabled → FanOutSignal
   │
   ▼
Phase 2 (NEW LOGIC): _dispatch_children becomes batch-aware
   groups = existing per_device / chunked split
   batches = slices of `groups`, `approval.batch_size` groups per slice
   for each batch i:
       if approval gate applies (see §7 rules):
           - short DB session: status="paused", write approval_state,
             debug_message = human summary, current_node_id = inventory node
           - await ctx.aio_wait_for_event("workflow-run.{uuid}.batch.{i}", …)
           - refresh run; if auto_approve_remaining was set → no more gates
           - status="running"
       dispatch this batch's children (existing gather + max_concurrency
       semaphore, scoped to the batch)
       accumulate child_results
       incremental _aggregate_and_persist(final=False)  ← results visible in UI
   │
   ▼
Phase 3 (unchanged shape): final _aggregate_and_persist(final=True)
Phase 4 (unchanged): resume_after_join for fan-in node, once, at the very end
```

Key properties:

- **Batch = `batch_size` dispatch groups.** In `per_device` mode a group is one device,
  so `batch_size: 10` = "10 devices per approval, run in parallel (children), bounded by
  `max_concurrency`". In `chunked` mode a group is one chunk; the natural setting is
  `chunk_size: 10, batch_size: 1` = "one 10-device chunk per approval".
- The **fan-in node still runs exactly once** at the end — git exports keep their
  one-pull/one-commit/one-push guarantee.
- Step results are re-aggregated after every batch, so the operator can inspect
  per-device outcomes of finished batches **while the run is paused**.
- Cancel needs no new code: `RunService.cancel_run` already accepts `paused` runs and
  cancels the Hatchet run, which aborts the durable wait.

---

## 5. Data model & config changes

### 5.1 Fan-out config extension (inventory step `pluginConfig`)

```jsonc
"fan_out": {
  "enabled": true,
  "mode": "chunked",
  "chunk_size": 10,
  "max_concurrency": 0,
  "approval": {                  // NEW — optional block
    "enabled": false,            // default: current behaviour (no gates)
    "batch_size": 1,             // dispatch groups per approval batch, min 1
    "first_batch_auto": true     // true: Run click implicitly approves batch 1
  }
}
```

Sanitisation mirrors the existing fields: `batch_size = max(1, int(...))`,
booleans via `bool(...)`. Absent/malformed `approval` ⇒ treated as disabled.

### 5.2 `workflow_runs.approval_state` column (NEW)

`backend/core/models/runs.py::WorkflowRun` gains:

```python
# Wait & Run: populated while a fan-out run is between approval batches.
# None on non-approval runs and cleared when the run reaches a terminal status.
approval_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```

Shape (authored only by the orchestrator; frontend treats it read-only):

```jsonc
{
  "awaiting": true,                 // true only while status == "paused" for approval
  "next_batch_index": 1,            // 0-based index of the batch waiting for release
  "total_batches": 10,
  "batches_completed": 1,
  "devices_total": 100,
  "devices_completed": 10,          // devices in finished batches
  "devices_failed": 0,              // devices in failed child workflows so far
  "next_batch_device_names": ["r11", "r12", "..."],  // display names, cap at 25 entries
  "auto_approve_remaining": false   // set by POST /runs/{id}/approve-all
}
```

Why a JSON column instead of discrete columns: the state is written/read as one unit by
exactly two parties (orchestrator writes, UI reads), it never needs to be queried or
indexed field-by-field, and it avoids a five-column migration.

**Immutability rule:** always assign a *new* dict
(`run.approval_state = {**old, "awaiting": False}`) — never mutate in place — so
SQLAlchemy JSON change detection fires without `flag_modified`.

### 5.3 Migration

New file `backend/migrations/versions/015_add_run_approval_state.py`, modelled on
`014_add_canvas_groups.py`:

```python
ADD_APPROVAL_STATE_COLUMN = """
ALTER TABLE workflow_runs
ADD COLUMN IF NOT EXISTS approval_state JSONB
"""

class Migration(BaseMigration):
    @property
    def name(self) -> str:
        return "015_add_run_approval_state"

    @property
    def description(self) -> str:
        return "Add approval_state column to workflow_runs for Wait & Run batching"

    def upgrade(self) -> dict[str, Any]:
        with self.engine.begin() as conn:
            conn.execute(text(ADD_APPROVAL_STATE_COLUMN))
        return {"columns_added": ["workflow_runs.approval_state"]}
```

Nullable, no default — existing rows and non-approval runs stay `NULL`.

### 5.4 Repository & response models

- `RunRepository.update_run_status`: add keyword `approval_state: dict | None = None`
  (apply when not `None`; to explicitly clear pass a sentinel — simplest: add a second
  keyword `clear_approval_state: bool = False`). In the existing
  `if status in TERMINAL_RUN_STATUSES:` block, also set `run.approval_state = None` so
  finished/cancelled runs never carry stale approval data.
- `backend/models/runs.py`: add `approval_state: dict | None = None` to
  `WorkflowRunSummary` and `WorkflowRunResponse`; map it in
  `run_service.py::_run_to_summary` and `_run_to_response`.

---

## 6. Backend orchestration changes

All in `backend/hatchet/workflows/workflow_run.py` unless noted.

### 6.1 Shared fan-out metadata helper (prep refactor)

The `_fan_out` metadata copy is currently duplicated in **four** inventory executors
(`get_nautobot_devices`, `get_git_devices`, `get_ise_devices`, `get_from_list` —
`grep -rn "_fan_out" backend/workflow_steps/`). Adding the `approval` sub-dict four
times invites drift. First extract:

```python
# backend/workflow_steps/common/fan_out.py  (NEW — pure helper, importable per the
# workflow_steps/common exemption in doc/WORKFLOW-STEPS.md)

def build_fan_out_metadata(fan_out_cfg: dict, node_id: str) -> dict | None:
    """Sanitise a step's fan_out pluginConfig into the _fan_out metadata dict.

    Returns None when fan-out is disabled/absent.
    """
    if not bool((fan_out_cfg or {}).get("enabled", False)):
        return None
    approval_cfg: dict = fan_out_cfg.get("approval") or {}
    return {
        "enabled": True,
        "mode": fan_out_cfg.get("mode", "per_device"),
        "chunk_size": max(1, int(fan_out_cfg.get("chunk_size", 1))),
        "max_concurrency": max(0, int(fan_out_cfg.get("max_concurrency", 0))),
        "inventory_node_id": node_id,
        "approval": {
            "enabled": bool(approval_cfg.get("enabled", False)),
            "batch_size": max(1, int(approval_cfg.get("batch_size", 1))),
            "first_batch_auto": bool(approval_cfg.get("first_batch_auto", True)),
        },
    }
```

Replace the inline `metadata_update["_fan_out"] = {...}` block in all four executors
with this helper. Behavioural no-op for existing configs (verify with the existing
executor tests, e.g. `tests/test_get_from_list_executor.py`,
`tests/test_get_ise_devices_executor.py` — extend them for the `approval` key).

### 6.2 Event key + lookback constant

```python
# Rename the constant — it now guards both debug stepping and batch approval.
STEP_EVENT_LOOKBACK = timedelta(minutes=15)   # was DEBUG_STEP_EVENT_LOOKBACK

def batch_approval_event_key(run_uuid: str, batch_index: int) -> str:
    return f"workflow-run.{run_uuid}.batch.{batch_index}"
```

Put `batch_approval_event_key` where both the worker and `RunService` can import it
without pulling worker-only deps — recommend a tiny module
`backend/services/execution/run_events.py` that also hosts the existing debug step key
format (`f"workflow-run.{uuid}.step.{node_id}"`), so key formats live in exactly one
place. Update `_run_steps_until_fan_out_or_done`, `execute_steps` (fan-out debug pause)
and `RunService._push_continue_event` to use it.

### 6.3 `_dispatch_children` becomes batch-aware

New signature (called from `execute_steps` phase 2 — pass `ctx` and the run uuid
through; capture `run.uuid` before the phase-1 session closes):

```python
async def _dispatch_children(
    signal: FanOutSignal,
    parent_run_id: int,
    *,
    ctx: DurableContext,
    run_uuid: str,
    canvas_nodes: list[dict[str, Any]],
    canvas_edges: list[dict[str, Any]],
) -> list[dict[str, Any] | BaseException]:
```

Logic (pseudocode; existing group-building and gather/semaphore code is reused
verbatim, just scoped to one batch):

```python
groups = <existing per_device / chunked split>
approval = signal.fan_out_config.get("approval") or {}
approval_enabled = bool(approval.get("enabled"))
batch_size = max(1, int(approval.get("batch_size", 1)))
first_batch_auto = bool(approval.get("first_batch_auto", True))

if not approval_enabled:
    <existing behaviour, unchanged — single gather over all groups>
    return results

batches = [groups[i : i + batch_size] for i in range(0, len(groups), batch_size)]
all_results: list[dict | BaseException] = []
auto_approve = False
devices_completed = devices_failed = 0

for batch_index, batch_groups in enumerate(batches):
    gate_needed = not auto_approve and not (batch_index == 0 and first_batch_auto)

    if gate_needed:
        with SessionLocal() as db:                       # short-lived session
            run_repo = RunRepository(db)
            run, _ = run_repo.get_run_by_id(parent_run_id)
            state = _build_approval_state(...)           # §5.2 shape, awaiting=True
            run_repo.update_run_status(
                run,
                status="paused",
                current_node_id=signal.inventory_node_id,  # canvas focus target
                debug_message=_approval_pause_message(...),  # human summary, see below
                approval_state=state,
            )
        event_key = batch_approval_event_key(run_uuid, batch_index)
        logger.info("Approval pause run_id=%s batch=%d/%d", parent_run_id,
                    batch_index + 1, len(batches))
        await ctx.aio_wait_for_event(
            event_key, scope=event_key, lookback_window=STEP_EVENT_LOOKBACK
        )
        with SessionLocal() as db:
            run_repo = RunRepository(db)
            run, _ = run_repo.get_run_by_id(parent_run_id)
            auto_approve = bool((run.approval_state or {}).get("auto_approve_remaining"))
            run_repo.update_run_status(
                run,
                status="running",
                approval_state={**(run.approval_state or {}), "awaiting": False},
            )

    batch_results = <existing gather/semaphore dispatch, over batch_groups only>
    all_results.extend(batch_results)
    devices_completed += <count devices in batch_groups>
    devices_failed += <devices in batch_groups whose child result is an exception>

    # Make finished batches inspectable while the next gate is up:
    with SessionLocal() as db:
        _aggregate_and_persist(
            run_repo=RunRepository(db), run_id=parent_run_id, signal=signal,
            canvas_nodes=canvas_nodes, canvas_edges=canvas_edges,
            child_results=all_results, final=False,
        )

return all_results
```

Pause message format (goes into `debug_message`, shown verbatim in the UI banner):

```
Batch {done}/{total} finished ({ok} device(s) ok, {failed} failed). Waiting for
approval to run batch {next} ({n} device(s): r11, r12, …). Click "Run next batch"
to continue or Cancel to stop.
```

Notes:

- `max_concurrency` keeps its meaning *within* a batch. Batches themselves are strictly
  sequential when approval is enabled.
- The final phase-3 `_aggregate_and_persist(..., final=True)` call in `execute_steps`
  stays where it is and receives the full accumulated `child_results` — identical to
  today for the non-approval path.
- Debug mode (`run_mode == "debug"`) still pauses **once before the whole fan-out
  dispatch** (existing block in `execute_steps`). Both gates can coexist: the debug
  pause fires first, then approval pauses between batches. No special-casing needed —
  event keys don't collide (`.step.` vs `.batch.` namespaces).
- The 24 h `execution_timeout` on `execute_steps` bounds the *total* run including
  human wait time — same constraint debug pauses already have. Document in the UI copy
  ("runs waiting for approval expire after 24 h"); do not change the timeout in v1.

### 6.4 `_aggregate_and_persist(final: bool = True)`

Add the keyword. When `final=False`:

- **Skip** the branch that marks outcome-less child-branch nodes as `skipped` (they are
  simply *not run yet*; leave their step results `pending`).
- Nodes **with** outcomes get their merged output + status written exactly as today —
  merging is recomputed from scratch from the accumulated `child_results` list, so the
  incremental calls are idempotent and the final call overwrites them consistently.
- Ignore the returned `merged_outcomes` at intermediate call sites (only the final call
  feeds `resume_after_join`).

`final=True` behaviour is byte-for-byte the current behaviour.

---

## 7. API changes

`backend/routers/workflow_runs.py` + `backend/services/execution/run_service.py`.

### 7.1 New endpoints

```python
@router.post("/runs/{run_id}/approve-batch", response_model=WorkflowRunResponse,
             dependencies=[Depends(require_permission("workflows", "execute"))])
async def approve_batch(...) -> WorkflowRunResponse:
    return service.approve_batch(run_id=run_id, user_id=current_user.id)

@router.post("/runs/{run_id}/approve-all", response_model=WorkflowRunResponse,
             dependencies=[Depends(require_permission("workflows", "execute"))])
async def approve_all(...) -> WorkflowRunResponse:
    return service.approve_all(run_id=run_id, user_id=current_user.id)
```

Service logic (mirror `step_run` / `continue_run` structure, including
`_assert_workflow_access` and 404 handling):

```python
def approve_batch(self, run_id: int, user_id: int) -> WorkflowRunResponse:
    run, username = <load or 404>; <access check>
    state = run.approval_state or {}
    if run.status != "paused" or not state.get("awaiting"):
        raise HTTPException(409, detail=f"Run is not awaiting batch approval "
                                        f"(status={run.status!r})")
    self._push_batch_event(run, int(state["next_batch_index"]))
    return <response>

def approve_all(self, run_id: int, user_id: int) -> WorkflowRunResponse:
    <same guards>
    run = self.run_repo.update_run_status(
        run, status="paused",
        approval_state={**state, "auto_approve_remaining": True},
    )
    self._push_batch_event(run, int(state["next_batch_index"]))
    return <response>

def _push_batch_event(self, run: WorkflowRun, batch_index: int) -> None:
    # identical error handling to _push_continue_event (raise_internal_server_error)
    event_key = batch_approval_event_key(run.uuid, batch_index)
    hatchet.event.push(event_key, {}, scope=event_key)
```

The "flag first, push second" order in `approve_all` matters: the worker re-reads
`approval_state` immediately after the wait resolves.

### 7.2 Tighten the debug endpoints

`step_run` and `continue_run` currently guard only on `status == "paused"` +
`current_node_id`. An approval pause also satisfies both, and a stray "Next Step" call
would push a `.step.` event nobody is waiting on (harmless but confusing) — and
`continue_run` would silently flip `run_mode`. Add to both:

```python
if run.approval_state is not None and run.approval_state.get("awaiting"):
    raise HTTPException(409, detail="Run is awaiting batch approval, not a debug step")
```

Conversely the approval endpoints require `approval_state.awaiting` (§7.1), so the four
endpoints are mutually exclusive by construction.

### 7.3 Cancel

No change. `cancel_run` already accepts `paused`, cancels the Hatchet run (killing the
durable wait), and `update_run_status(..., "cancelled")` clears `approval_state` via the
terminal-status branch (§5.4).

---

## 8. Frontend changes

### 8.1 Shared fan-out config component (prep refactor)

The fan-out block (`enabled` switch, `mode` select, `chunk_size`, `max_concurrency`) is
duplicated in **four** ConfigPanels:
`workflow-steps/get-nautobot-devices/index.tsx`, `get-git-devices/index.tsx`,
`get-ise-devices/index.tsx`, `get-from-list/index.tsx`. Extract it once into

```
frontend/src/components/features/workflow-steps/shared/fan-out-config.tsx
```

as `<FanOutConfigSection value={fanOut} onChange={...} />`, preserving the exact current
markup/styling (teal palette, card anatomy — `doc/WORKFLOW-STEPS-STYLE_GUIDE.md`
"fan-out config block"). Port the existing `sanitizeFanOut`-style normalisation
(currently ~lines 43–64 of `get-nautobot-devices/index.tsx`) into the shared file and
extend its type:

```typescript
export interface FanOutApprovalConfig {
  enabled: boolean;
  batch_size: number;        // min 1
  first_batch_auto: boolean;
}
export interface FanOutConfig {
  enabled: boolean;
  mode: "per_device" | "chunked";
  chunk_size: number;
  max_concurrency: number;
  approval: FanOutApprovalConfig;
}
```

New controls inside the block (visible only when `fan_out.enabled`):

- **"Wait for approval between batches"** — `Switch` → `approval.enabled`.
- When on:
  - **"Groups per batch"** — number input, min 1 → `approval.batch_size`, with helper
    text: *"per_device mode: devices per batch · chunked mode: chunks per batch"*.
  - **"Run first batch immediately"** — `Switch`, default on → `approval.first_batch_auto`.

Replace the duplicated block in all four ConfigPanels with the shared component; verify
no visual change with approval off.

### 8.2 Types & mutations

- `components/features/workflows/types/workflow-runs.ts`: add
  `approval_state?: ApprovalState | null` to the run summary/detail types, with
  `ApprovalState` mirroring §5.2.
- `hooks/queries/use-workflow-run-mutations.ts`: add `useApproveBatchMutation` and
  `useApproveAllMutation`, copied from `useStepRunMutation` (same invalidations, same
  409-refresh comment/behaviour), posting to `runs/${runId}/approve-batch` /
  `runs/${runId}/approve-all`. Toasts: "Batch released" / "Running all remaining
  batches".

No new query hooks: the existing run polling (`useWorkflowRunQuery`) already refetches
while a run is active, and `paused` is already treated as active
(`workflow-executions-panel.tsx` `canCancel`, status icon).

### 8.3 Topbar buttons (`workflow-topbar.tsx`)

Alongside the existing debug pair, keyed on the approval state instead of `runMode`:

```typescript
const approval = activeRun?.approval_state;
const isAwaitingBatch = activeRun?.status === "paused" && approval?.awaiting === true;
```

When `isAwaitingBatch` (takes precedence over `isAwaitingStep` — they are mutually
exclusive per §7.2, but guard anyway):

- **`Run next batch (k/N)`** button (`Play`/`StepForward` icon) →
  `approveBatch.mutate(activeRunId)`, label using
  `approval.next_batch_index + 1` / `approval.total_batches`.
- **`Run all remaining`** button (`FastForward` icon) →
  `approveAll.mutate(activeRunId)`.

### 8.4 Executions panel (`workflow-executions-panel.tsx`)

The amber `debug_message` banner in `RunRow` already displays the pause summary (the
orchestrator writes the human text there — §6.3). Add, next to the Cancel button, the
same two buttons when `run.status === "paused" && run.approval_state?.awaiting` — this
covers operators reviewing a run without it being the builder's `activeRunId`. Show
`next_batch_device_names` (comma-joined, truncated) in the expanded `RunDetail` header
so the operator sees exactly which devices are about to be touched.

---

## 9. Rules & edge cases

| Case | Behaviour |
|---|---|
| `approval.enabled: false` (default / legacy configs) | Byte-for-byte current fan-out behaviour. |
| Approval enabled, no fan-in node | Fine — batches gate the child dispatch; there is simply no phase 4. |
| Approval enabled + git steps **not** behind a fan-in | Same hazard as today (documented in WORKFLOW-STEPS.md); approval does not change it. Sequential batches reduce but don't eliminate races — keep recommending the fan-in node. |
| Child failure inside a batch | Loop continues to the next gate regardless (proceed-with-survivors, consistent with existing fan-out semantics). The failure count appears in `approval_state`/pause message; the operator decides: approve, or cancel. No automatic abort in v1. |
| Debug mode + approval | Debug pauses once before dispatch (existing block), then approval gates apply per batch. Distinct event namespaces (`.step.` / `.batch.`); endpoint guards (§7.2) keep the two UIs mutually exclusive. |
| Double click on "Run next batch" | Second push targets the same key/scope; the worker consumes one wait and has moved on — the extra event is scoped to a batch index that will never be waited on again. Harmless. The 409 guard rejects clicks after the run resumed (mirrors the existing stray-click comment in `useStepRunMutation`). |
| Click racing wait registration | Covered by `scope` + `STEP_EVENT_LOOKBACK`, same as debug stepping. |
| Backend restart / worker crash mid-wait | Hatchet durable task semantics — same guarantees (and limitations) as an in-flight debug pause today. No new handling in v1. |
| Run cancelled while paused | Existing `cancel_run` path; `approval_state` cleared by the terminal-status branch. |
| 24 h `execution_timeout` | Total run time including waits. Mention in help text; unchanged in v1. |
| `approval.batch_size` ≥ number of groups | Single batch; with `first_batch_auto: true` no gate ever fires — behaves like approval off. |
| `first_batch_auto: false` | Gate before batch 0 too — run pauses immediately after the parent branch reaches fan-out ("arm, then fire"). |

---

## 10. Testing plan

Backend (pytest, in-memory SQLite where possible — model on
`tests/test_debug_mode_stepping.py`, which already fakes `DurableContext`):

1. **`tests/test_fan_out_metadata.py`** — `build_fan_out_metadata`: disabled/absent
   config → `None`; defaults; sanitisation (`batch_size` clamped to ≥1); approval block
   passthrough. Extend the four executor tests to assert the `approval` key.
2. **`tests/test_wait_and_run_dispatch.py`** — drive `_dispatch_children` with a fake
   `ctx` whose `aio_wait_for_event` records keys and returns immediately:
   - approval off → no waits, all children dispatched (regression guard);
   - `first_batch_auto: true`, 3 batches → waits for `.batch.1`, `.batch.2` only;
   - `first_batch_auto: false` → waits for `.batch.0` first;
   - `auto_approve_remaining` set between waits → no further waits;
   - run rows: `paused`+`approval_state.awaiting` before wait, `running`+
     `awaiting: false` after; terminal status clears `approval_state`;
   - intermediate aggregation: after batch 1 of 2, batch-1 nodes have merged output,
     untouched nodes remain `pending` (not `skipped`).
3. **`tests/test_run_service_approval.py`** — endpoint guards: 409 when not paused /
   not awaiting; `approve_all` sets the flag before pushing; debug `step_run` /
   `continue_run` 409 on an approval pause and vice versa; event key format matches
   `run_events.batch_approval_event_key`.
4. **`_aggregate_and_persist(final=False)`** unit test: no `skipped` marking.

Frontend: type-check (`tsc`) + lint; manual verification below. (Playwright journey
optional, via e2e-runner, once the flow is stable.)

**Manual end-to-end verification** (per project rule — confirm the change works):

1. `python -m pytest` in `backend/`; run the regression guard scripts.
2. Start backend + Hatchet worker + frontend; migration 015 applies on startup
   (check `app.log` for `015_add_run_approval_state`).
3. Build a workflow: `get-from-list` (cheap, no Nautobot needed) with ~6 fake devices,
   fan-out `per_device`, approval `{enabled, batch_size: 2, first_batch_auto: true}` →
   `log-message` step.
4. Run. Expect: batch 1 (2 devices) executes; run turns `paused` with amber banner
   "Batch 1/3 finished…"; step results for the 2 devices inspectable.
5. Click **Run next batch** → batch 2 runs → pauses again. Click **Run all remaining**
   → run completes without further pauses; final statuses/aggregation identical to a
   non-approval run of the same workflow.
6. Re-run and **Cancel** while paused → run `cancelled`, `approval_state` null in
   `GET /api/runs/{id}`.
7. Run once in **Debug** mode with approval on → debug pause before fan-out, then batch
   pauses; "Next Step" buttons never appear during a batch pause and vice versa.
8. Run a workflow with approval **off** → behaviour and timings unchanged (regression).

---

## 11. Implementation order (checklist)

Work top-to-bottom; each stage leaves the tree green.

1. [x] **Prep refactor (backend):** `workflow_steps/common/fan_out.py::build_fan_out_metadata`;
       switch all four inventory executors to it; extend executor tests. *(No behaviour change.)*
2. [x] **Prep refactor (backend):** `services/execution/run_events.py` with both event-key
       builders; rename `DEBUG_STEP_EVENT_LOOKBACK` → `STEP_EVENT_LOOKBACK`; update
       `workflow_run.py` + `run_service.py` call sites. *(No behaviour change.)*
3. [x] **Prep refactor (frontend):** shared `<FanOutConfigSection>`; swap into the four
       ConfigPanels. *(No visual change.)*
4. [x] Migration `015_add_run_approval_state` + `WorkflowRun.approval_state` model column.
5. [x] `RunRepository.update_run_status` approval_state handling + terminal clear;
       Pydantic run models + `_run_to_summary`/`_run_to_response`.
6. [x] `_aggregate_and_persist(final=...)` parameter.
7. [x] Batch-aware `_dispatch_children` + `execute_steps` call-site changes (pass `ctx`,
       `run_uuid`, canvas nodes/edges).
8. [x] `RunService.approve_batch` / `approve_all` / `_push_batch_event`; router endpoints;
       tighten `step_run`/`continue_run` guards.
9. [x] Backend tests (§10.1–4); `ruff check .`; regression guard scripts.
10. [x] Frontend types + mutations; topbar buttons; executions-panel buttons/banner;
        approval controls in `<FanOutConfigSection>`; help-panel updates for the four
        inventory steps (document approval semantics + 24 h note).
11. [x] `doc/WORKFLOW-STEPS.md`: extend the *Fan-out execution* section with the approval
        config and a pointer to this document.
12. [ ] Manual end-to-end verification (§10) — all eight scenarios.
