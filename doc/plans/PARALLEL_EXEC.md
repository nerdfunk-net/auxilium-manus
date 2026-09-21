# Parallel execution of independent canvas branches — resume note

Not a plan yet — this is a briefing to pick the discussion back up in a fresh
session with full context. Written 2026-09-21, right after removing per-node
debug mode (`feature/remove-debug`, see git log / `REMOVE_DEBUG_MODE_HOWTO.md`
for that unrelated piece of work).

## The question

Given a canvas shape like:

```
        ┌─► b1 ─┐
   a ───┤        ├─► c
        └─► b2 ─┘
```

`b1` and `b2` have no data dependency on each other (both only depend on
`a`). Can the engine run them concurrently instead of one after the other?

## Where things stand today (verified, not guessed)

- **Answer: no.** `StepRunner.execute_all()` / the Hatchet-side mirror
  `_run_steps_until_fan_out_or_done` (`hatchet/workflows/workflow_run/phase1.py`)
  walk the topologically-sorted node list in a single Python `for` loop,
  one node at a time, inside one Hatchet task (`execute_steps`). `b1` then
  `b2`, always sequential, regardless of the graph shape.
- **`c` "waiting" for both parents is free, not a synchronization
  primitive.** `_assemble_input_context` merges whatever's in `step_outcomes`
  for `c`'s parent edges; because the walk is sequential and topologically
  ordered, both parents are guaranteed already-run by the time `c`'s turn
  comes up. Correctness comes from ordering, not from a wait/join.
- **Fan-out is the only real concurrency in the engine, and it's
  device-level, not branch-level.** Enabling fan-out on an inventory step
  spawns one Hatchet **child workflow** (`DeviceGroupExecution`) per
  device/chunk, run concurrently via `asyncio.gather` + an optional
  `asyncio.Semaphore` (`hatchet/workflows/workflow_run/fan_out_dispatch.py::_run_groups`).
  But **each child still walks its own downstream subgraph sequentially** —
  same one-node-at-a-time loop, just once per device instead of once for the
  whole run. So fan-out parallelizes "the same branch across N devices,"
  never "different branches for the same device." (Documented in
  `doc/HOWTO_BUILD_WORKFLOWS.md` → "Fan-out parallelizes devices, not
  independent branches", added this session.)
- **Native Hatchet DAG (`.task(parents=[...])`) doesn't fit.** Hatchet's own
  task graph is declared once at **worker startup** (see `prepare_task →
  execute_steps` in `hatchet/workflows/workflow_run/__init__.py` — the
  *only* place `parents=` is used in this codebase). Canvas graphs are
  per-workflow, user-edited, arbitrary, and change at save time with no
  redeploy — mapping that onto per-node Hatchet tasks would mean generating
  and re-registering Hatchet workflow definitions per save, which is a much
  larger and more fragile undertaking than the actual goal warrants (we
  already have a taste of how painful "restart a worker to pick up a
  definition change" is, from the background-tier's `dynamic_worker.py`
  self-restart-on-poll mechanism — doing that per canvas edit is a
  different order of magnitude).
- **A hand-rolled in-process scheduler is the right shape**, using the same
  pattern already proven in this codebase for fan-out:
  `asyncio.gather()` (or `asyncio.TaskGroup`, Python 3.11+, we're on 3.14)
  plus an `asyncio.Semaphore` for a concurrency cap, mirroring
  `fan_out_dispatch.py::_run_groups`. No new dependency needed — reaching
  for Dask/Prefect/Celery/etc. was considered and rejected (redundant with
  Hatchet, fights both frameworks' assumptions about who owns
  retries/state).

## Concrete risks identified when this gets built

1. **Shared `SQLAlchemy Session` across concurrent branches.** `StepRunner`
   holds one `self.db`/`self.repo` for the whole run; `run_node_in_sequence`
   → `self.repo.update_step_result(...)` is a **synchronous** call
   (`repositories/run_repository.py`, not `async def`) on that shared
   `Session`. `Session` is not safe for interleaved concurrent use. Fan-out
   already solved this correctly once — each `DeviceGroupExecution` child
   opens its **own** `SessionLocal()`
   (`hatchet/workflows/device_group_execution.py`) rather than sharing one.
   A sibling-node scheduler needs the same discipline: a fresh
   `Session`/`StepRunner` per concurrently-running branch, not one shared
   across the `gather`.
2. **`DeviceSessionPool` is actually fine** — checked directly:
   `services/network/netmiko/session_pool.py` keys each pooled connection
   with its own `asyncio.Lock` (plus a `_pool_lock` on the pool dict), so two
   concurrently-scheduled steps hitting the *same* device just serialize
   safely at that layer. No corruption risk, just (correctly) no speedup for
   that pair.
3. **Debug-mode pausing used to be a real obstacle here — it no longer is.**
   Per-node debug pausing was removed in this same session
   (`feature/remove-debug`), specifically flagged at the time as "the part
   of the engine that doesn't compose with concurrent scheduling." That
   obstacle is now gone — one less thing this work has to design around.
4. **Failure semantics need an explicit decision**, matching the
   already-established "proceed with survivors" policy used everywhere else
   in this engine (`_blocked_by_upstream_failure`, partial fan-out results):
   `gather(..., return_exceptions=True)`, not `TaskGroup`'s default
   all-or-nothing cancellation — unless individually wrapped.
5. **No prior art for multiple concurrently-"running" `WorkflowStepResult`
   rows on the same run.** Fan-out children don't even write step-result
   rows until aggregated after the fact (`execute_subgraph` docstring: "without
   writing WorkflowStepResult records"). A sibling-node scheduler would be
   the first case where two rows are genuinely `"running"` at once for one
   run — worth checking the run-detail frontend's assumptions before
   shipping (polling, per-node UI state, anything keyed on "at most one
   running step").

## Sizing

Rough estimate from the earlier discussion: **Medium** — a few focused days.
Touches: `services/execution/step_runner/runner.py` (`execute_all`,
`run_node_in_sequence` → needs a concurrent/ready-set variant),
`hatchet/workflows/workflow_run/phase1.py` (`_run_steps_until_fan_out_or_done` —
now that debug-mode's per-node pause is gone, this function is structurally
identical to `StepRunner.execute_all`; worth deduplicating *before* or
*as part of* this work rather than maintaining two copies of a scheduler),
plus whatever the concurrent-Session and run-detail-UI findings above turn
into.

## Open questions to resolve when this discussion resumes

- Always-parallelize independent branches when the topology allows it, or a
  new opt-in switch (like `fan_out.enabled`) — given every existing
  concurrency knob in this app (`fan_out.max_concurrency`,
  background-tier `concurrency_limit`) is explicit, opt-in, and
  user-configured, should sibling-branch parallelism follow the same
  pattern, or is "parallelize whenever the graph shape allows it" safe
  enough to be the unconditional default?
- Does a concurrency cap matter here the way `fan_out.max_concurrency` does
  for devices, or is the fan-out (device count) axis the only one where an
  uncapped burst is actually dangerous (SSH/TACACS+ thundering herd), making
  branch-level parallelism inherently low-cardinality and safe to leave
  uncapped?
- What does the run-detail UI need to change, if anything, once two step
  results can legitimately be `"running"` at the same time?
