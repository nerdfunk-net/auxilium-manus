# Review — `STEPRUNNER_WORKFLOWRUN.md` refactoring plan

**Date:** 2026-09-06
**Reviewer:** Grok 4.6
**Plan:** `doc/refactoring/STEPRUNNER_WORKFLOWRUN.md` (proposal, 2026-09-06)
**Scope:** `backend/services/execution/step_runner.py` (1016 lines) and
`backend/hatchet/workflows/workflow_run.py` (959 lines) — the workflow-execution
hot path.

This is a review of the *plan*, checked against the current modules, their
importers, and the unit/integration tests that pin their behaviour. It is not
an implementation.

---

## 0. Verdict

**Phases 0–2 are a valid, implementable, no-behaviour-change split.** They will
not change the Hatchet protocol, the DB schema, or the public import paths
callers use. The technique (file → package, re-exports, thin delegators, lazy
DB imports left inside functions) is the correct conservative posture for this
code.

**Phase 3 is the part that can actually break the engine. Do not do it in the
same effort.** Item 1 (unify the four topological walks) is a behaviour rewrite
dressed as cleanup and should be treated as later / never, not “optional in
this PR.”

The plan is right about the diagnosis and the constraints it did find
(`child_workflow` object identity, lazy `SessionLocal`, `_plugin_registry_service`
as a single `@lru_cache`, Hatchet registration at package import). Several of
its safety claims are wrong. Those are the places a careful implementation
would still get hurt.

---

## 1. Breaking changes

**None for production callers**, if Phases 1–2 stay literal moves:

- `from services.execution.step_runner import StepRunner / FanOutSignal / classify_step_exception`
  still works
- `from hatchet.workflows.workflow_run import workflow / build_workflow_execution / WorkflowRunInput`
  still works
- Hatchet still registers `WorkflowExecution` (`prepare` → `execute_steps`) at
  import of the package `__init__`
- No migrations, no payload-shape changes, no step-executor contract changes

**There are internal breaks the plan does not list.** Under its own rule
(“if a test needs editing, stop”), Phase 1e would stop.

### 1.1 Patch paths — Phase 1e will fail as written

`backend/tests/unit/test_step_runner_device_sessions.py` patches names that
live on the **module**, not on `StepRunner`:

```python
patch("services.execution.step_runner.pre_step_guard")
patch("services.execution.step_runner.post_step_guard")
patch("services.execution.step_runner.effective_produces")
patch("services.execution.step_runner.capability_spec_from_plugin")
```

After the class moves to `runner.py`, those names are
`services.execution.step_runner.runner.*`. The planned `__init__.py` only
re-exports `StepRunner`, `FanOutSignal`, and `classify_step_exception`. The
test will call the real guards and fail.

This is not a behaviour change. It is a unittest patch-target change. The
“zero test edits” rule is too strict here — distinguish **behaviour** from
**where a name is bound**. Either:

- re-export those four names from `step_runner/__init__.py`, or
- allow that one test to retarget `…step_runner.runner.…`.

Safe as-is (already patched at the source module):

- `patch("services.execution.step_registry.STEP_REGISTRY", …)` — lazy import
  inside `_execute_step`
- `patch("core.database.SessionLocal", …)` — stays safe only if the lazy
  in-function import is preserved

### 1.2 `child_workflow` identity — the plan is correct

`test_wait_and_run_dispatch.py` does
`patch.object(wf_run_module.child_workflow, "aio_run", …)`. That patches the
**object**, not a string path. Re-exporting the same
`device_group_execution.child_workflow` from the package `__init__` keeps that
working, because `_run_groups` will still call methods on that same object.

Do not create a second `hatchet.workflow(...)` in the new package.

### 1.3 Logger names change

Every `logging.getLogger(__name__)` moves from
`services.execution.step_runner` / `hatchet.workflows.workflow_run` to
`…step_runner.runner`, `…step_runner.subgraph`, `…workflow_run.phase1`, etc.

Runtime behaviour is unchanged. `core/logging_config.py` keys off ancestor
prefixes (`services.execution`, `workflow_steps`), so worker logs still land.
It is still an observable difference; do not treat `__name__` as a stable API.

### 1.4 No API / protocol / data-model break

Production importers of these two modules, re-checked 2026-09-06:

| Caller | Import |
|---|---|
| `hatchet/worker.py` | `workflow as workflow_execution` |
| `hatchet/dynamic_worker.py` | `build_workflow_execution` |
| `hatchet/workflows/dispatch.py` | `WorkflowRunInput`, `workflow` |
| `hatchet/workflows/scheduled_trigger.py` | `WorkflowRunInput`, `workflow` |
| `services/execution/run_service.py` | lazy `WorkflowRunInput` |
| `hatchet/workflows/device_group_execution.py` | lazy `StepRunner`, calls `execute_subgraph` |

Plan §2.1 missed `backend/tests/integration/test_workflow_run_end_to_end.py`
(`StepRunner.execute_all`). That is a test importer, not a production break.

---

## 2. Is the plan valid?

**Yes, as a structural refactor.** These files are large because many concerns
sit together, not because there is a hidden god-object that must be redesigned.
The execution model (canvas vs definition vs run, phase-1 walk, fan-out
children, Wait & Run, aggregate, post-join resume) should not change.

### 2.1 What the plan gets right

- File → package so every existing `from X import Y` keeps resolving
- Thin `StepRunner._resolve_funnels = staticmethod(...)` so tests that call
  private staticmethods keep working
- `workflow_run` import graph is one-directional (`fan_out_dispatch` →
  `batch_approval` + `aggregation`; leaves import nothing)
- `_dispatch_with_approval` stays with `_run_groups` / `_aggregate_and_persist`
  so you do not create a cycle
- Lazy `from core.database import SessionLocal` stays inside task functions —
  required for worker import order and for `patch("core.database.SessionLocal")`
- `_plugin_registry_service` stays a single `@lru_cache` — do not copy it into
  two modules
- Registration (`workflow = build_workflow_execution(name="WorkflowExecution")`)
  stays in package `__init__`, so `import hatchet.worker` still registers the
  same workflow

### 2.2 What is overstated

**“The existing suite is the primary gate” and it is already strong.** It is
strong for graph resolution and for two orchestrator helpers. It is weak on
the paths this split actually moves.

| Path | Tests today |
|---|---|
| Funnels, disabled steps, executable filter, blocked-by-upstream | Solid unit coverage |
| `_run_steps_until_fan_out_or_done` (debug + normal) | Solid |
| `_dispatch_children` / Wait & Run | Solid |
| `_aggregate_and_persist` | Solid |
| `classify_step_exception` / persist-on-error | Solid |
| **`execute_subgraph`** | **No unit test** |
| **`resume_after_join`** | **No unit test** |
| **`_finalize_fan_out_parent`** | **No unit test** |
| **`execute_steps` glue** (phase1 → dispatch → finalize) | **No unit test** |
| **`execute_all`** | Integration only (linear, no fan-out); production no longer uses it |

The plan cites `test_fan_out_metadata.py` as the Phase 1d (`subgraph.py`) gate.
That file tests `workflow_steps.common.fan_out.build_fan_out_metadata`. It
never calls `execute_subgraph`. Fan-out children are the multi-device heart of
the app, and they are the least-tested piece about to be moved.

Phase 0 is therefore not optional polish. The `fanout_no_join` /
`fanout_with_join` fingerprints are the first real net around
`execute_subgraph` and `resume_after_join`. If those two cases are shallow or
stubbed badly, Phase 1d is a blind move.

---

## 3. Is it implementable?

**Yes.** It is mechanical. A few instructions in the doc would produce a broken
intermediate commit or a circular import if followed literally.

### 3.1 Circular import (Phase 1e)

Final `step_runner/__init__.py` does
`from …runner import StepRunner` first. If `runner.py` then does:

```python
from services.execution.step_runner import FanOutSignal  # package, still loading
```

Python will raise `ImportError` on a partially initialized package.
`FanOutSignal` and `classify_step_exception` must be imported from
`services.execution.step_runner.signals`, never from the package.

Same rule inside the package: always

```python
from services.execution.step_runner.graph_resolution import …
```

never

```python
from services.execution.step_runner import graph_resolution
```

### 3.2 Phase 1d vs pyright

1d’s `TYPE_CHECKING` block imports `StepRunner` from `runner.py`, which does
not exist until 1e. Runtime is fine (`TYPE_CHECKING` is false). `pyright`
after 1d, which the plan requires, will fail.

Point the `TYPE_CHECKING` import at the class still in `__init__` during 1d,
or land 1d+1e as one commit.

### 3.3 `git mv` order is wrong

The plan writes:

```
git mv step_runner.py step_runner/__init__.py
mkdir -p step_runner
```

The directory must exist first. Reverse those two lines (same for
`workflow_run.py`).

### 3.4 Line counts are wrong; the 800-line goal is still met

After extracting signals (~55), graph resolution (~240), and subgraph (~190)
from 1016 lines, `runner.py` is about **550–620 lines**, not 340. It still
holds `execute_all`, `resume_after_join`, `run_node_in_sequence`,
`_execute_and_persist_node`, `_assemble_input_context`, `_execute_step`, and
seed/store/serialize. That is under 800. Do not split `runner.py` further to
chase the estimate.

### 3.5 §6.3 registration snapshot

`Workflow` in hatchet-sdk 1.38.1 does have `.name` and `.tasks`. The
“adapt to SDK API” hedge is unnecessary, but the snapshot must assert on the
real task-config fields (`execution_timeout`, parents), not a guessed shape.

`python -c "import hatchet.worker"` also needs `HATCHET_CLIENT_TOKEN` — that
is already true today (`hatchet/client.py` constructs `Hatchet()` at import).

### 3.6 §6.4 Hypothesis

Hypothesis is not a project dependency. Use the fixed-corpus alternative, or
skip 6.4. Do not add Hypothesis for a one-commit equivalence check.

### 3.7 Characterization fixtures

Generate them on clean `main` **before** any move, and keep the fingerprint
free of `uuid4` error ids and timestamps (the sketched shape already does
this). Pin list order for `output_device_ids` / `executed_node_order` or the
fixture will flake. Drive the real entrypoints, not a reimplementation of the
walk.

---

## 4. Does it make sense?

**Phases 0–2: yes.** The files are over the 800-line ceiling, the seams the
plan cuts are real (graph resolution, subgraph walk, Hatchet wiring, fan-out
dispatch, batch approval, aggregation), and the technique (re-export +
delegator) is the lowest-risk way to split this.

**Do not expect this to make the engine safer.** It makes files navigable. The
four topological walks (`execute_all`, `resume_after_join`, `execute_subgraph`,
`_run_steps_until_fan_out_or_done`) remain duplicated. That duplication is
already the drift risk. Splitting files does not fix it; it only makes each
copy easier to find.

**Phase 3: no, not now, and item 1 maybe never.**

1. **Unify the four walks.** Those walks are not the same skeleton. One
   persists and hard-stops on raise, one records errors and continues, one
   skips `allowed_node_ids` and does not write `WorkflowStepResult`, one
   injects a durable debug pause and can return a fan-out signal. A shared
   `_walk(...)` is exactly where a silent skip/status/fan-out bug would hide.
2. **Drop injected `SessionLocal` / repository parameters.** Those exist so
   tests and `execute_steps` can pass the same objects. Removing them is a
   small cleanup and a new patch-path minefield. Separate PR, low value.
3. **Migrate tests to submodule paths and delete shims.** Do this years later,
   if ever. The shims are the compatibility contract.

The older FABLE note (`doc/analysis/FABLE_BACKEND_20260902.md` §6.1) wanted
new types (`ExecutionPlanner`, `NodeExecutor`, `SubgraphRunner`). That is a
redesign. This plan correctly does **not** do that. Keep it that way.

---

## 5. Required before anyone starts

1. **Approve only Phases 0–2.** Phase 3 is out of scope, written down as
   “later / never,” not “optional in this PR.”
2. **Phase 0 must include real `execute_subgraph` + `resume_after_join`
   fingerprints**, not only `_run_steps_until_fan_out_or_done`. Without those,
   the riskiest move (1d) has no net.
3. **Add the four guard names to the import-surface test**, and decide
   patch-path vs re-export before 1e.
4. **Inside the new packages, never import from the package `__init__`.**
   Sibling modules only.
5. **Do not hoist a single lazy import.** Especially `SessionLocal`,
   `StepRunner`, `FanOutSignal`, `STEP_REGISTRY`. Worker import time and test
   patches both depend on this.
6. **Do not “improve” while moving** — no signature cleanup, no shared
   `_walk`, no renaming `_resolve_funnels` except via delegator.

If those hold, this is a boring, correct refactor. The engine’s behaviour
lives in the function bodies, and those stay byte-equivalent. The mistakes
that would matter here are almost all import-graph and patch-target mistakes,
not algorithm mistakes — and those are exactly the ones the current draft
still under-specifies.

---

## 6. Plan-doc corrections (checklist)

Use this when editing `doc/refactoring/STEPRUNNER_WORKFLOWRUN.md` before
implementation:

- [ ] §2.1: add `tests/integration/test_workflow_run_end_to_end.py`
- [ ] §2.2: add the four `services.execution.step_runner.{pre,post}_step_guard`
      / `effective_produces` / `capability_spec_from_plugin` patch targets
- [ ] §3.1: `runner.py` estimated ~550–620 lines, not ~340
- [ ] §5 Phase 1a / 2a: `mkdir` before `git mv`
- [ ] §5 Phase 1d: `TYPE_CHECKING` import must not point at `runner.py` until
      1e exists (or combine 1d+1e)
- [ ] §5 Phase 1d verification: drop `test_fan_out_metadata.py`; require the
      Phase 0 `fanout_*` fingerprints instead
- [ ] §5 Phase 1e: sibling imports only (`signals`, `graph_resolution`,
      `subgraph`) — never `from services.execution.step_runner import X`
      from inside the package
- [ ] §6.1: state honestly that `execute_subgraph` / `resume_after_join` /
      `_finalize_fan_out_parent` / `execute_steps` have no unit tests today
- [ ] §6.4: drop Hypothesis, or mark it “fixed corpus only”
- [ ] §9 / Phase 3: mark out of scope for this work
