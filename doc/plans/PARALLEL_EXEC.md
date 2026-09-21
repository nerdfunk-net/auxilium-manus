# Parallel execution of independent canvas branches — resolved

This was a resume note (written 2026-09-21, right after removing per-node
debug mode). It's now implemented, on `feature/parallel-steps`:

- `services/execution/graph.py::topological_generations` groups a
  topologically-sorted node list into dependency layers.
- `StepRunner._run_wave` (`services/execution/step_runner/runner.py`) runs one
  layer's nodes concurrently via `asyncio.gather(..., return_exceptions=True)`;
  `execute_all` (phase 1) and `resume_after_join` (phase 4) both walk layers
  through it instead of a flat node-at-a-time list.
- DB-write safety: no session-per-branch rewrite needed. Every
  `RunRepository.update_step_result`/`create_step_result` write already
  self-commits, so a single `asyncio.Lock` on `StepRunner`
  (`_persist_step_result`) around each write is sufficient — it never brackets
  a sibling's actual step work (SSH, HTTP), only the write itself.
- `subgraph.run_subgraph` (fan-out children) is also converted — same
  generation walk, via a new `_run_one_subgraph_node` helper (no lock needed
  there, since it writes zero `WorkflowStepResult` rows during the walk; the
  parent persists after aggregating). Both concurrency axes — devices (fan-out)
  and independent branches (this work) — now compose everywhere in the engine.

See `doc/HOWTO_BUILD_WORKFLOWS.md` → "Independent branches run concurrently"
for the user-facing explanation, and
`tests/unit/test_step_runner_parallel_execution.py` for the behavioral tests
(concurrency actually observed, fan-in merge of distinct `output_key`s, the
existing merge-conflict guard still firing, a hard exception in one sibling
not stranding another, and `_blocked_by_upstream_failure` reading correctly
off wave-produced results).
