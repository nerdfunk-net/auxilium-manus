# Refactoring Plan — `step_runner.py` & `workflow_run.py`

**Status:** proposal, awaiting review — revised after Grok 4.6 review
**Author:** prepared 2026-09-06
**Scope:** split the two largest files on the workflow-execution hot path into
packages of small, single-purpose modules **without changing any runtime
behaviour or any import path**.

---

## 0. Revisions after Grok 4.6 review (2026-09-06)

Review: `doc/analysis/GROK_STEPRUNNER_WORKFLOWRUN.md`. All of its factual claims
were re-verified against the codebase and are correct. Changes folded in:

| # | Change | Section |
|---|---|---|
| R1 | **Phase 1 reordered** — move the class to `runner.py` *before* extracting `subgraph.py`, so `subgraph.py`'s `TYPE_CHECKING` import of `StepRunner` and the `pyright` gate never point at a not-yet-existing module. | §5 Phase 1 |
| R2 | **`test_step_runner_device_sessions.py` must be edited** in the class-move step: it does `patch("services.execution.step_runner.pre_step_guard")` (+ `post_step_guard`, `effective_produces`, `capability_spec_from_plugin`) — module-level names that move to `runner.py`. This is a **patch-target rebind, not a behaviour change**; it is listed explicitly and the "zero test edits" rule is narrowed to "zero *behavioural* test edits". | §2.2, §2.3, §5 |
| R3 | **`mkdir` before `git mv`** — the target package dir must exist first. | §5 Phase 1a / 2a |
| R4 | **Never `from services.execution.step_runner import X` (or `from hatchet.workflows.workflow_run import X`) inside the package.** Sibling modules import each other by full path (`from ....step_runner.signals import FanOutSignal`) or `import ... as`. Importing via the package re-enters a half-initialised `__init__` → `ImportError`. The 1c "Code after" snippet is corrected accordingly. | §2.3, §5 |
| R5 | **Coverage claim corrected.** `execute_subgraph`, `resume_after_join`, `_finalize_fan_out_parent`, and the `execute_steps` glue have **no unit tests today**. `test_fan_out_metadata.py` (cited as the Phase 1d gate) tests `build_fan_out_metadata`, not `execute_subgraph`. The Phase 0 `fanout_no_join` / `fanout_with_join` / post-join-resume fingerprints are therefore **mandatory pre-work**, not illustrative, and are the only net around the riskiest move. | §5, §6.1, §6.2 |
| R6 | **`runner.py` size estimate 340 → ~600** (still < 800). Do not split it further to chase the old number. | §3.1, §9 |
| R7 | **Drop Hypothesis** from §6.4 — not a project dependency. Fixed corpus only. | §6.4 |
| R8 | **§2.1 adds** `tests/integration/test_workflow_run_end_to_end.py` (imports `StepRunner.execute_all`; test importer, not a production break). | §2.1 |
| R9 | **Phase 3 is out of scope for this work** — "later / possibly never", not "optional in this PR". Unifying the four topological walks (item 1) is a behaviour rewrite: the walks are deliberately *not* the same skeleton (persist-and-hard-stop vs record-and-continue vs skip-`allowed_node_ids`-no-persist vs durable-debug-pause-with-fan-out-return). | §5 Phase 3, §9 |
| R10 | **Logger names change** (`logging.getLogger(__name__)` moves to `…runner`, `…subgraph`, `…phase1`, …). Runtime-safe — `core/logging_config.py` keys off ancestor prefixes (`services.execution`, `hatchet`) — but noted as an observable difference; `__name__` is not a stable API. | §2.3 |

---

## 1. Why

| File | Lines | Project ceiling (`rules/common/coding-style.md`) |
|---|---|---|
| `backend/services/execution/step_runner.py` | 1016 | 800 max |
| `backend/hatchet/workflows/workflow_run.py` | 959 | 800 max |

Neither file is a "god object" — both are already decomposed into small,
heavily-documented functions. The problem is purely that too many *distinct
concerns* live in one file:

* `step_runner.py` mixes **graph resolution** (funnels, disabled-step splicing,
  executable filtering, topological sort), **segment execution** (`execute_all`,
  `resume_after_join`, `execute_subgraph`), **blocked-by-upstream logic**,
  **context assembly / step dispatch**, and **serialization helpers**.
* `workflow_run.py` mixes **Hatchet task wiring**, **debug-mode stepping**,
  **fan-out dispatch planning**, **Wait & Run batch approval**, and **child
  result aggregation / persistence**.

This is the heart of the app. A regression here breaks every workflow run. The
plan is therefore built around one rule:

> **Every phase is a pure code move. No behaviour change, no signature change,
> no import-path change. The existing test suite is the pass/fail gate for each
> phase and must pass untouched.**

---

## 2. Hard constraints (discovered from the codebase)

These are the things a careless refactor would break. Every one is preserved by
the plan.

### 2.1 Public import paths still used elsewhere

```
hatchet/worker.py            from hatchet.workflows.workflow_run import workflow as workflow_execution
hatchet/dynamic_worker.py    from hatchet.workflows.workflow_run import build_workflow_execution
hatchet/workflows/scheduled_trigger.py  WorkflowRunInput, workflow as workflow_execution
hatchet/workflows/dispatch.py           WorkflowRunInput, workflow as workflow_execution
services/execution/run_service.py       from hatchet.workflows.workflow_run import WorkflowRunInput   (lazy, inside fn)
hatchet/workflows/device_group_execution.py   runner.execute_subgraph(...)
services/execution/step_registry.py  (imported BY step_runner, lazily)
```

Test importers that must also keep resolving (not production, but the gate):

```
tests/integration/test_workflow_run_end_to_end.py   StepRunner (calls execute_all; linear, no fan-out)
```

### 2.2 Symbols imported directly by tests (private names included)

| Symbol | Imported from | Test files |
|---|---|---|
| `StepRunner` | `services.execution.step_runner` | 6 files |
| `classify_step_exception` | `services.execution.step_runner` | `test_step_runner_errors.py` |
| `FanOutSignal` | `services.execution.step_runner` | `test_aggregate_and_persist_final.py`, `test_wait_and_run_dispatch.py` |
| `StepRunner._resolve_funnels` (staticmethod) | — | `test_step_runner_funnel.py` (×5) |
| `StepRunner._resolve_disabled_steps` (staticmethod) | — | `test_step_runner_disabled_steps.py` (×12) |
| `StepRunner._blocked_by_upstream_failure` (staticmethod) | — | `test_step_runner_blocked_by_failure.py` (×5) |
| `StepRunner._serialize_outcomes` (staticmethod) | — | `test_step_runner_serialize_outcomes.py` |
| `StepRunner._seed_run_inputs` (staticmethod) | — | `test_run_inputs_seeding.py` |
| `StepRunner._is_executable_node` / `build_execution_plan` | — | `test_canvas_decoration_execution_plan.py`, `test_step_runner_disabled_steps.py` |
| `_run_steps_until_fan_out_or_done` | `hatchet.workflows.workflow_run` | `test_step_runner_funnel.py`, `test_debug_mode_stepping.py` |
| `_aggregate_and_persist` | `hatchet.workflows.workflow_run` | `test_aggregate_and_persist_final.py` |
| `_dispatch_children` | `hatchet.workflows.workflow_run` | `test_wait_and_run_dispatch.py` |
| `workflow_run` module object + `.child_workflow` attr | `hatchet.workflows` | `test_wait_and_run_dispatch.py` — `patch.object(wf_run_module.child_workflow, "aio_run", ...)` |
| `services.execution.step_runner.pre_step_guard`, `.post_step_guard`, `.effective_produces`, `.capability_spec_from_plugin` (module-level names) | patched as string paths | `test_step_runner_device_sessions.py` — `patch("services.execution.step_runner.pre_step_guard")` etc., around a direct `runner._execute_step(...)` call |

**Consequence:** we convert each `.py` file into a **package** (`foo.py` →
`foo/__init__.py`). The `__init__.py` re-exports every symbol above, so all
imports — public and test-private — keep resolving from the original path. The
class keeps thin delegating `@staticmethod`s so `StepRunner._resolve_funnels`
still works.

**One unavoidable test edit.** The four `patch("services.execution.step_runner.<guard>")`
targets in `test_step_runner_device_sessions.py` bind to *module-level* names
that move into `runner.py` when the class moves. A string re-export in
`__init__.py` does **not** redirect them (the class calls the name bound in
`runner.py`, not the alias). That test must retarget those four strings to
`services.execution.step_runner.runner.<guard>`. This is a **patch-target
rebind, not a behaviour change** — see §2.3 for the narrowed rule.

### 2.3 Behavioural details that must not be disturbed

* **Lazy, in-function imports** (`from core.database import SessionLocal`
  inside a task fn) are deliberate — Hatchet worker import ordering and avoiding
  DB-engine creation at import time. **Do not hoist them to module level.**
* `patch("core.database.SessionLocal", ...)` in tests patches at source, so
  every submodule must keep importing `SessionLocal` lazily from
  `core.database`, never binding it at its own module top level.
* `test_wait_and_run_dispatch.py` reads `wf_run_module.child_workflow` — the
  package `__init__` must expose `child_workflow` as an attribute (re-export
  it) and the object identity must be the one from
  `hatchet.workflows.device_group_execution`.
* `_plugin_registry_service()` is `@lru_cache(maxsize=1)` — it must remain a
  single module-level cached function, not be duplicated per submodule.
* Hatchet registration side effects: `workflow = build_workflow_execution(
  name="WorkflowExecution")` runs at import of the package `__init__`, exactly
  as it runs today at import of the module. Task names (`prepare`,
  `execute_steps`), `parents=[prepare_task]`, timeouts (30 s / 24 h), and
  `on_events=["workflow:run"]` are unchanged.
* **No intra-package import through the package root.** Inside
  `step_runner/` and `workflow_run/`, a sibling module must import another
  sibling by its full path (`from services.execution.step_runner.signals
  import FanOutSignal`) or `import … as`, **never** `from
  services.execution.step_runner import FanOutSignal`. The package form
  re-enters `__init__.py` while it is still executing its own
  `from .runner import StepRunner` line, and `FanOutSignal` (defined *after*
  that line in `__init__`) is not yet bound → `ImportError` on a partially
  initialised package.
* **Logger names change** (each `logging.getLogger(__name__)` moves to
  `…step_runner.runner`, `…step_runner.subgraph`, `…workflow_run.phase1`, …).
  Runtime is unaffected — `core/logging_config.py` configures by ancestor
  prefix (`services.execution`, `hatchet`) — but it is an observable
  difference and `__name__` is not a stable API.

### 2.4 The "no test edits" rule, narrowed

Every phase is a pure code move: **no test may need a *behavioural* edit**
(different assertion, different expected status/order/output). If one does,
the step changed behaviour → revert.

The single permitted category of test edit is a **patch-target rebind**: a
`patch("some.module.name")` string that must follow a module-level name to its
new module. Exactly one such edit is known up front — the four guard targets
in `test_step_runner_device_sessions.py` (§2.2). Any *other* required test
edit is a red flag; stop and re-check.

---

## 3. Target structure

### 3.1 `services/execution/step_runner.py` → `services/execution/step_runner/`

```
services/execution/step_runner/
├── __init__.py          ~35 lines   re-exports: StepRunner, FanOutSignal, classify_step_exception
│                                    + the 4 guard names (see §2.2 patch targets)
├── signals.py           ~55 lines   FanOutSignal, classify_step_exception
├── graph_resolution.py  ~240 lines  _STRUCTURAL_KINDS, _is_author_disabled,
│                                    resolve_disabled_steps, resolve_funnels,
│                                    is_executable_node, filter_executable_graph, topological_sort
├── subgraph.py          ~190 lines  run_subgraph + 3 helpers (free fns taking `runner`)
└── runner.py            ~600 lines  class StepRunner (execute_all, run_node_in_sequence,
                                     _execute_and_persist_node, resume_after_join,
                                     _assemble_input_context, _execute_step, seed/store/serialize,
                                     create_pending_step_results, _step_requires_devices,
                                     _blocked_by_upstream_failure, + thin delegators)
                                     + module-level guard imports + _plugin_registry_service
```

Every file < 800; the largest is `runner.py` at ~600 (1016 − signals ~35 −
graph_resolution ~210 − subgraph ~175 + ~30 delegator stubs). **Do not split
`runner.py` further to chase a smaller number** — the walk/dispatch/guard core
belongs together.

### 3.2 `hatchet/workflows/workflow_run.py` → `hatchet/workflows/workflow_run/`

```
hatchet/workflows/workflow_run/
├── __init__.py          ~95 lines   WorkflowRunInput, prepare, execute_steps,
│                                    build_workflow_execution, workflow (static registration),
│                                    re-exports: _run_steps_until_fan_out_or_done,
│                                    _aggregate_and_persist, _dispatch_children, child_workflow
├── phase1.py            ~185 lines  _maybe_debug_pause_before_node, _fan_out_context_if_requested,
│                                    _run_steps_until_fan_out_or_done, _debug_pause_before_fan_out,
│                                    _phase1_run_or_early_finish
├── fan_out_dispatch.py  ~280 lines  _FanOutDispatchPlan, _parse_fan_out_dispatch, _build_child_inputs,
│                                    _run_groups, _tally_batch_failures,
│                                    _dispatch_with_approval, _dispatch_children
├── batch_approval.py    ~135 lines  MAX_APPROVAL_STATE_DEVICE_NAMES, _build_approval_state,
│                                    _format_approval_pause_message, _batch_needs_approval_gate,
│                                    _device_names_for_groups, _wait_and_resume_batch_approval
└── aggregation.py       ~155 lines  _aggregate_and_persist, _finalize_fan_out_parent
```

**Import direction (no cycles):**
`__init__` → `phase1`, `fan_out_dispatch`, `aggregation`
`fan_out_dispatch` → `batch_approval`, `aggregation`
`phase1`, `batch_approval`, `aggregation` → siblings: none.

> Note: `_dispatch_with_approval` and `_dispatch_children` stay **together** in
> `fan_out_dispatch.py` (not in `batch_approval.py`) precisely to keep the
> import graph one-directional — `_dispatch_with_approval` needs `_run_groups`
> and `_aggregate_and_persist`, while `batch_approval.py` stays a leaf of pure
> helpers + the one `_wait_and_resume_batch_approval` coroutine.

---

## 4. Symbol-to-home map

### 4.1 step_runner

| Current symbol | New home | Access preserved via |
|---|---|---|
| `FanOutSignal` | `signals.py` | `__init__` re-export |
| `classify_step_exception` | `signals.py` | `__init__` re-export |
| `_STRUCTURAL_KINDS`, `_is_author_disabled` | `graph_resolution.py` | internal |
| `_resolve_disabled_steps` | `graph_resolution.resolve_disabled_steps` | `StepRunner._resolve_disabled_steps` staticmethod delegates |
| `_resolve_funnels` | `graph_resolution.resolve_funnels` | `StepRunner._resolve_funnels` staticmethod delegates |
| `_is_executable_node` | `graph_resolution.is_executable_node(node, registry)` | `StepRunner._is_executable_node` method delegates (passes `self.plugin_registry`) |
| `_filter_executable_graph` | `graph_resolution.filter_executable_graph(nodes, edges, registry)` | `StepRunner._filter_executable_graph` method delegates |
| `_topological_sort` | `graph_resolution.topological_sort(nodes, edges, registry)` | `StepRunner._topological_sort` method delegates |
| `execute_subgraph` + `_subgraph_node_blocked` + `_execute_one_subgraph_node` + `_record_subgraph_node_error` | `subgraph.py` (free fns, first arg `runner`) | `StepRunner.execute_subgraph` method delegates |
| `_plugin_registry_service` (`@lru_cache`) | `runner.py` | unchanged (module-level in `runner.py`) |
| `StepRunner` class, everything else | `runner.py` | `__init__` re-export |

### 4.2 workflow_run

| Current symbol | New home | Access preserved via |
|---|---|---|
| `WorkflowRunInput`, `prepare`, `execute_steps`, `build_workflow_execution`, `workflow` | `__init__.py` | stays at package root |
| `MAX_APPROVAL_STATE_DEVICE_NAMES` | `batch_approval.py` | (only used there) |
| `_maybe_debug_pause_before_node`, `_fan_out_context_if_requested`, `_run_steps_until_fan_out_or_done`, `_debug_pause_before_fan_out`, `_phase1_run_or_early_finish` | `phase1.py` | `__init__` re-exports `_run_steps_until_fan_out_or_done` |
| `_FanOutDispatchPlan`, `_parse_fan_out_dispatch`, `_build_child_inputs`, `_run_groups`, `_tally_batch_failures`, `_dispatch_with_approval`, `_dispatch_children` | `fan_out_dispatch.py` | `__init__` re-exports `_dispatch_children` + `child_workflow` |
| `_build_approval_state`, `_format_approval_pause_message`, `_batch_needs_approval_gate`, `_device_names_for_groups`, `_wait_and_resume_batch_approval` | `batch_approval.py` | internal |
| `_aggregate_and_persist`, `_finalize_fan_out_parent` | `aggregation.py` | `__init__` re-exports `_aggregate_and_persist` |

---

## 5. Phased execution

Each numbered sub-step is **one commit**. After every commit:

```
cd backend
python -m pytest -q
python scripts/check_asyncio_run.py
python scripts/check_http_500_leaks.py
python scripts/check_router_repositories.py
python scripts/check_text_sql.py
ruff check services/execution/step_runner hatchet/workflows/workflow_run
pyright services/execution/step_runner hatchet/workflows/workflow_run
```

The suite must be **green and unchanged** (same test count, same names), with
the one known patch-target exception in §2.4. If any *other* test needs
editing to pass, stop — that means behaviour or API changed and the step is
wrong.

### Phase 0 — Safety net (no production code touched)

See §6. Add characterization tests + import-surface guard + coverage baseline.
Commit. **Do not proceed until Phase 0 is green.**

---

### Phase 1 — `step_runner.py` → package

> **Order note (R1):** the class moves into `runner.py` in **1d**, *before*
> `subgraph.py` is extracted in **1e**. `subgraph.py` needs a `TYPE_CHECKING`
> import of `StepRunner` from `runner.py`, and the per-step `pyright` gate
> would fail if `runner.py` did not exist yet. (Original draft had these
> swapped.)

#### 1a. Convert file to package (mechanical)

```
mkdir -p backend/services/execution/step_runner
git mv backend/services/execution/step_runner.py \
       backend/services/execution/step_runner/__init__.py
```

**Code before** — `services/execution/step_runner.py` (one 1016-line module).

**Code after** — `services/execution/step_runner/__init__.py` (identical
content, byte-for-byte). Nothing else changes. Python treats
`services.execution.step_runner` as a package; every existing
`from services.execution.step_runner import X` still resolves.

*Verification:* full suite green, zero diff in behaviour. This commit exists
so the next ones are small.

#### 1b. Extract `signals.py`

**Code before** (`__init__.py`, lines ~46–92):

```python
@dataclass
class FanOutSignal:
    """Returned by execute_all when an inventory step requests fan-out."""
    inventory_node_id: str
    fan_out_config: dict[str, Any]
    inventory_outcome: WorkflowContext
    step_outcomes: dict[str, dict[str, WorkflowContext]] = field(default_factory=dict)
    join_node_id: str | None = None


logger = logging.getLogger(__name__)

_STRUCTURAL_KINDS = frozenset({"fan-in"})
# ...

def classify_step_exception(exc: Exception) -> tuple[str, str]:
    # ...
    if isinstance(exc, ValueError):
        return "configuration", str(exc) or "This step's configuration is invalid."
    if isinstance(exc, RuntimeError):
        return "execution", str(exc) or "This step failed to complete."
    return "internal", "An unexpected internal error occurred while running this step."
```

**Code after** — new file `services/execution/step_runner/signals.py`:

```python
"""Return-value types for the step runner, kept in their own module so the
Hatchet layer (`hatchet/workflows/workflow_run/`) can import `FanOutSignal`
and `classify_step_exception` without pulling in the whole StepRunner class.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from models.workflow_context import WorkflowContext


@dataclass
class FanOutSignal:
    """Returned by execute_all when an inventory step requests fan-out."""
    inventory_node_id: str
    fan_out_config: dict[str, Any]
    inventory_outcome: WorkflowContext
    step_outcomes: dict[str, dict[str, WorkflowContext]] = field(default_factory=dict)
    join_node_id: str | None = None


def classify_step_exception(exc: Exception) -> tuple[str, str]:
    """Map a raised exception to (error_category, user-facing message).
    ... (docstring copied verbatim) ...
    """
    if isinstance(exc, ValueError):
        return "configuration", str(exc) or "This step's configuration is invalid."
    if isinstance(exc, RuntimeError):
        return "execution", str(exc) or "This step failed to complete."
    return "internal", "An unexpected internal error occurred while running this step."
```

**Code after** — `services/execution/step_runner/__init__.py` top:

```python
from services.execution.step_runner.signals import FanOutSignal, classify_step_exception
# ... rest of the class module, with the FanOutSignal + classify_step_exception
#     definitions deleted (now imported above)
```

`workflow_run` currently does `from services.execution.step_runner import
FanOutSignal` / `classify_step_exception` — still works via the re-export.

*Verification:* `test_step_runner_errors.py` (imports `classify_step_exception`
from `services.execution.step_runner`) green, unchanged.

#### 1c. Extract `graph_resolution.py`

Move `_STRUCTURAL_KINDS`, `_is_author_disabled`, and the bodies of
`_resolve_disabled_steps`, `_resolve_funnels`, `_is_executable_node`,
`_filter_executable_graph`, `_topological_sort` into free functions. The
executable-filter functions currently read `self.plugin_registry`; the free
functions take it as an explicit parameter.

**Code before** (`__init__.py`):

```python
class StepRunner:
    @staticmethod
    def _resolve_funnels(nodes, edges):
        funnel_ids = {n["id"] for n in nodes if ...}
        # ~50 lines
        return remaining_nodes, resolved_edges

    def _is_executable_node(self, node: dict[str, Any]) -> bool:
        if _is_author_disabled(node):
            return False
        data = node.get("data") or {}
        kind = data.get("kind", "")
        if not kind:
            return True
        plugin = self.plugin_registry.get_plugin(kind)
        if plugin is None:
            return True
        return plugin.executable

    def _topological_sort(self, nodes, edges):
        executable_nodes, executable_edges = self._filter_executable_graph(nodes, edges)
        return topological_order(executable_nodes, executable_edges)
```

**Code after** — new file `services/execution/step_runner/graph_resolution.py`:

```python
"""Pure canvas-graph resolution: splice out funnel nodes and author-disabled
steps, drop non-executable decorations, and produce the executable-filtered
topological order. No DB, no StepRunner state — the plugin registry is passed
in explicitly.

Extracted from step_runner so the "what graph do we actually walk" logic has
one home and can be unit-tested in isolation (it already is — see
test_step_runner_funnel.py / test_step_runner_disabled_steps.py).
"""
from __future__ import annotations

from typing import Any

from services.execution.graph import topological_order
from services.plugin_registry.plugin_registry_service import PluginRegistryService

_STRUCTURAL_KINDS = frozenset({"fan-in"})


def _is_author_disabled(node: dict[str, Any]) -> bool:
    data = node.get("data") or {}
    return data.get("disabled") is True and data.get("kind") not in _STRUCTURAL_KINDS


def resolve_disabled_steps(nodes, edges):
    # body copied verbatim from StepRunner._resolve_disabled_steps
    ...


def resolve_funnels(nodes, edges):
    # body copied verbatim from StepRunner._resolve_funnels
    ...


def is_executable_node(node: dict[str, Any], registry: PluginRegistryService) -> bool:
    if _is_author_disabled(node):
        return False
    data = node.get("data") or {}
    kind = data.get("kind", "")
    if not kind:
        return True
    plugin = registry.get_plugin(kind)
    if plugin is None:
        return True
    return plugin.executable


def filter_executable_graph(nodes, edges, registry):
    executable_nodes = [n for n in nodes if is_executable_node(n, registry)]
    executable_ids = {n["id"] for n in executable_nodes if "id" in n}
    executable_edges = [
        e for e in edges
        if e.get("source", "") in executable_ids and e.get("target", "") in executable_ids
    ]
    return executable_nodes, executable_edges


def topological_sort(nodes, edges, registry):
    executable_nodes, executable_edges = filter_executable_graph(nodes, edges, registry)
    return topological_order(executable_nodes, executable_edges)
```

**Code after** — `StepRunner` keeps **thin delegators** so every test and the
`load_execution_graph` internals are untouched. Note the import form (R4):
`import … as`, **not** `from services.execution.step_runner import
graph_resolution` (that re-enters the package `__init__`):

```python
import services.execution.step_runner.graph_resolution as _gr


class StepRunner:
    # kept for external / test callers — pure delegation, no behaviour change
    _resolve_disabled_steps = staticmethod(_gr.resolve_disabled_steps)
    _resolve_funnels = staticmethod(_gr.resolve_funnels)

    def _is_executable_node(self, node: dict[str, Any]) -> bool:
        return _gr.is_executable_node(node, self.plugin_registry)

    def _filter_executable_graph(self, nodes, edges):
        return _gr.filter_executable_graph(nodes, edges, self.plugin_registry)

    def _topological_sort(self, nodes, edges):
        return _gr.topological_sort(nodes, edges, self.plugin_registry)

    def load_execution_graph(self, workflow):
        nodes = workflow.canvas_nodes or []
        edges = workflow.canvas_edges or []
        nodes, edges = _gr.resolve_funnels(nodes, edges)
        return _gr.resolve_disabled_steps(nodes, edges)
```

*Verification:* `test_step_runner_funnel.py` (calls
`StepRunner._resolve_funnels(nodes, edges)` directly, ×5),
`test_step_runner_disabled_steps.py` (×12),
`test_canvas_decoration_execution_plan.py` (`runner._is_executable_node`),
`test_execution_graph.py` — all green, unchanged.

#### 1d. Move the class into `runner.py` (R1 — before subgraph extraction)

```
# create services/execution/step_runner/runner.py
# move into it, verbatim: the module docstring, all imports (including the
#   module-level `from services.workflow_context.guards import
#   pre_step_guard, post_step_guard` etc.), _plugin_registry_service
#   (@lru_cache, stays a single definition), and class StepRunner
#   (with the 1b/1c delegators already on it).
```

**Code after** — `services/execution/step_runner/__init__.py` becomes
re-export only. It must re-export **the four guard names too** (R2), because
`test_step_runner_device_sessions.py` patches them as
`services.execution.step_runner.<name>` string paths:

```python
"""Executes all steps of a workflow run in topological order.
... (module docstring stays on runner.py; a short one here) ...
"""
from __future__ import annotations

from services.execution.step_runner.runner import (
    StepRunner,
    # re-exported ONLY so existing patch("services.execution.step_runner.<x>")
    # targets in test_step_runner_device_sessions.py keep importing; the class
    # itself calls the copy bound in runner.py, so tests still retarget — see below
    capability_spec_from_plugin,
    effective_produces,
    post_step_guard,
    pre_step_guard,
)
from services.execution.step_runner.signals import FanOutSignal, classify_step_exception

__all__ = [
    "StepRunner", "FanOutSignal", "classify_step_exception",
    "pre_step_guard", "post_step_guard", "effective_produces",
    "capability_spec_from_plugin",
]
```

**Required test edit (R2, patch-target rebind only).** In
`test_step_runner_device_sessions.py`, the four
`patch("services.execution.step_runner.pre_step_guard")` /
`post_step_guard` / `effective_produces` / `capability_spec_from_plugin`
strings become `patch("services.execution.step_runner.runner.<name>")`. The
class in `runner.py` calls the name bound in `runner.py`; a re-export alias in
`__init__` is *not* the object it calls, so the string must point at
`runner`. No assertion in that test changes.

*Verification:* full suite green **except** that one test file's four patch
strings (edit them in the same commit). `import hatchet.worker` still works
(it imports `StepRunner` lazily inside `device_group_execution`).

#### 1e. Extract `subgraph.py`

The fan-out-child subgraph walk (`execute_subgraph` +
`_subgraph_node_blocked` + `_execute_one_subgraph_node` +
`_record_subgraph_node_error`, ~175 lines) needs a lot of runner internals
(`_assemble_input_context`, `_execute_step`, `_seed_run_inputs`,
`_store_step_outcomes`, `_step_requires_devices`,
`_blocked_by_upstream_failure`). Move it out of `runner.py` as free functions
whose first argument is the `StepRunner` instance.

**Code before** (`runner.py`, after 1d):

```python
class StepRunner:
    async def execute_subgraph(
        self, *, run, workflow, initial_context, inventory_node_id, allowed_node_ids
    ) -> tuple[dict[str, dict[str, WorkflowContext]], dict[str, dict[str, str]]]:
        nodes, edges = self.load_execution_graph(workflow)
        ordered_nodes = self._topological_sort(nodes, edges)
        step_outcomes = {inventory_node_id: {"success": initial_context}}
        step_errors = {}
        blocked_nodes = set()
        for node in ordered_nodes:
            node_id = node.get("id", "")
            if node_id not in allowed_node_ids:
                continue
            # ... blocked check, execute, record-error ...
        return step_outcomes, step_errors
```

**Code after** — new file `services/execution/step_runner/subgraph.py`:

```python
"""Fan-out child execution: run only the allowed downstream subgraph, without
writing WorkflowStepResult rows (the parent aggregates and persists). Split
out of the StepRunner class because it is a self-contained second walk with
its own bookkeeping; it reuses the runner's per-node primitives via an
explicit `runner` handle rather than `self`.
"""
from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from models.workflow_context import StepOutcome, WorkflowContext
from services.execution.step_runner.signals import classify_step_exception

if TYPE_CHECKING:
    # runner.py exists as of 1d — safe. TYPE_CHECKING is False at runtime,
    # so this never triggers an import cycle.
    from services.execution.step_runner.runner import StepRunner

logger = logging.getLogger(__name__)


async def run_subgraph(
    runner: "StepRunner", *, run, workflow, initial_context,
    inventory_node_id, allowed_node_ids,
):
    nodes, edges = runner.load_execution_graph(workflow)
    ordered_nodes = runner._topological_sort(nodes, edges)
    # ... body copied verbatim, `self.` → `runner.` ...
    return step_outcomes, step_errors


def _subgraph_node_blocked(runner, *, node_id, step_type, edges, step_outcomes, blocked_nodes, run_id): ...
async def _execute_one_subgraph_node(runner, *, run, workflow, node_id, step_type, step_config, edges, step_outcomes): ...
def _record_subgraph_node_error(runner, *, node_id, step_type, run_id, exc, step_errors, step_outcomes, initial_context): ...
```

**Code after** — `runner.py` keeps a 3-line delegator (import form per R4):

```python
import services.execution.step_runner.subgraph as _subgraph


class StepRunner:
    async def execute_subgraph(self, *, run, workflow, initial_context,
                               inventory_node_id, allowed_node_ids):
        return await _subgraph.run_subgraph(
            self, run=run, workflow=workflow, initial_context=initial_context,
            inventory_node_id=inventory_node_id, allowed_node_ids=allowed_node_ids,
        )
```

*Verification (R5):* `device_group_execution.py` calls
`runner.execute_subgraph(...)` — the delegator preserves it. **There is no
unit test of `execute_subgraph` today** — `test_fan_out_metadata.py` tests
`workflow_steps.common.fan_out.build_fan_out_metadata`, a different function.
The gate for this step is the Phase 0 `fanout_no_join` / `fanout_with_join`
fingerprints (§6.2) plus `tests/integration/test_workflow_run_end_to_end.py`.
If those fingerprints are not in place, **do not do 1e.**

*Final sizes:* `step_runner/__init__.py` ≈ 40, `runner.py` ≈ 600 (R6),
`graph_resolution.py` ≈ 240, `subgraph.py` ≈ 190, `signals.py` ≈ 55.

---

### Phase 2 — `workflow_run.py` → package

#### 2a. Convert file to package (mechanical)

```
mkdir -p backend/hatchet/workflows/workflow_run
git mv backend/hatchet/workflows/workflow_run.py \
       backend/hatchet/workflows/workflow_run/__init__.py
```

**Code before:** one 959-line module.
**Code after:** identical bytes at `workflow_run/__init__.py`. All 6 importers
(§2.1) and the test imports (§2.2) still resolve.

*Verification:* `python -m pytest -q`, plus explicitly import a worker:
`python -c "import hatchet.worker"` (exercises the static registration path).
That import constructs `Hatchet()` (via `hatchet/client.py`), so it needs the
`HATCHET_CLIENT_*` env the test env already provides for
`test_hatchet_workers.py` — no new requirement.

#### 2b. Extract `aggregation.py`

**Code before** (`__init__.py`, lines ~309–378 and ~851–959):

```python
async def _finalize_fan_out_parent(*, run_id, signal, canvas_nodes, canvas_edges,
                                   child_results, SessionLocal, RunRepository,
                                   WorkflowRepository, StepRunner) -> str:
    with SessionLocal() as db:
        ...
        success, child_merged = _aggregate_and_persist(...)
        if signal.join_node_id is not None:
            ...
            post_join_runner = StepRunner(db)
            try:
                join_success = await post_join_runner.resume_after_join(...)
            finally:
                await post_join_runner.close_device_sessions()
            success = success and join_success
        ...
    return final_status


def _aggregate_and_persist(*, run_repo, run_id, signal, canvas_nodes, canvas_edges,
                           child_results, final: bool = True):
    from models.workflow_context import WorkflowContext
    from services.execution.graph import child_node_ids
    from services.workflow_context.merge import merge_fan_out_contexts
    from services.workflow_context.secret_fields import redact_secrets_in_data
    # ~100 lines
    return not (has_any_failure or any_node_failed), merged_outcomes
```

**Code after** — new file `hatchet/workflows/workflow_run/aggregation.py`:
same two functions, verbatim bodies, **lazy imports kept inside the
functions**. `_finalize_fan_out_parent` keeps its `SessionLocal=…,
RunRepository=…, …` injected-parameter signature (do **not** simplify it in
this phase — that is Phase 3).

**Code after** — `__init__.py`:

```python
from hatchet.workflows.workflow_run.aggregation import (
    _aggregate_and_persist,
    _finalize_fan_out_parent,
)
```

*Verification:* `test_aggregate_and_persist_final.py` imports
`_aggregate_and_persist` from `hatchet.workflows.workflow_run` — green via
re-export.

#### 2c. Extract `batch_approval.py`

Move `MAX_APPROVAL_STATE_DEVICE_NAMES`, `_build_approval_state`,
`_format_approval_pause_message`, `_batch_needs_approval_gate`,
`_device_names_for_groups`, `_wait_and_resume_batch_approval`.

**Code before** (`__init__.py`, lines ~461–515, ~625–714):

```python
MAX_APPROVAL_STATE_DEVICE_NAMES = 25

def _build_approval_state(*, awaiting, next_batch_index, total_batches, ...):
    return { "awaiting": awaiting, ... }

async def _wait_and_resume_batch_approval(*, signal, parent_run_id, ctx, run_uuid,
                                          batch_index, total_batches, devices_completed,
                                          devices_failed, batch_device_names, devices_total,
                                          SessionLocal, RunRepository) -> bool:
    state = _build_approval_state(...)
    message = _format_approval_pause_message(...)
    with SessionLocal() as db:
        ...
    await ctx.aio_wait_for_event(event_key, scope=event_key, lookback_window=STEP_EVENT_LOOKBACK)
    with SessionLocal() as db:
        ...
    return auto_approve_remaining
```

**Code after** — new file
`hatchet/workflows/workflow_run/batch_approval.py`: those symbols verbatim.
`_wait_and_resume_batch_approval` keeps the `SessionLocal=…, RunRepository=…`
injected params. Imports `STEP_EVENT_LOOKBACK`, `batch_approval_event_key`
from `services.execution.run_events` at module top (already safe — no DB).

No re-export needed (no test imports these directly today) — but add
`_build_approval_state` and `_wait_and_resume_batch_approval` to `__init__`'s
re-export block anyway for discoverability and to keep
`from hatchet.workflows.workflow_run import *` stable.

#### 2d. Extract `fan_out_dispatch.py`

Move `_FanOutDispatchPlan`, `_parse_fan_out_dispatch`, `_build_child_inputs`,
`_run_groups`, `_tally_batch_failures`, `_dispatch_with_approval`,
`_dispatch_children`. Add `from hatchet.workflows.device_group_execution
import DeviceGroupInput, child_workflow` at module top of `fan_out_dispatch.py`.

**Code before** (`__init__.py`, lines ~517–609, ~717–848):

```python
@dataclass(frozen=True)
class _FanOutDispatchPlan:
    groups: list[list[str]]
    max_concurrency: int
    approval_enabled: bool
    approval_cfg: dict[str, Any]
    device_ids: list[str]
    all_devices: dict[str, Any]

async def _run_groups(signal, *, parent_run_id, all_devices, max_concurrency,
                      group_list, index_offset):
    child_inputs = _build_child_inputs(...)
    if max_concurrency <= 0:
        tasks = [child_workflow.aio_run(inp) for inp in child_inputs]
        return list(await asyncio.gather(*tasks, return_exceptions=True))
    semaphore = asyncio.Semaphore(max_concurrency)
    ...

async def _dispatch_with_approval(signal, *, parent_run_id, ctx, run_uuid,
                                  canvas_nodes, canvas_edges, plan):
    from core.database import SessionLocal
    from repositories.run_repository import RunRepository
    ...
    for batch_index, batch_groups in enumerate(batches):
        if _batch_needs_approval_gate(...):
            auto_approve_remaining = await _wait_and_resume_batch_approval(...)
        batch_results = await _run_groups(...)
        ...
        with SessionLocal() as db:
            _aggregate_and_persist(run_repo=RunRepository(db), ..., final=False)
    return all_results

async def _dispatch_children(signal, parent_run_id, *, ctx, run_uuid,
                             canvas_nodes, canvas_edges):
    plan = _parse_fan_out_dispatch(signal)
    if not plan.groups:
        return []
    if not plan.approval_enabled:
        return await _run_groups(signal, ...)
    return await _dispatch_with_approval(signal, ..., plan=plan)
```

**Code after** — new file
`hatchet/workflows/workflow_run/fan_out_dispatch.py`:

```python
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from hatchet.workflows.device_group_execution import DeviceGroupInput, child_workflow
from hatchet.workflows.workflow_run.aggregation import _aggregate_and_persist
from hatchet.workflows.workflow_run.batch_approval import (
    _batch_needs_approval_gate,
    _device_names_for_groups,
    _wait_and_resume_batch_approval,
)
from services.execution.run_events import STEP_EVENT_LOOKBACK

logger = logging.getLogger(__name__)

# ... all seven symbols, verbatim bodies, lazy `from core.database import ...`
#     kept inside _dispatch_with_approval ...
```

**Code after** — `__init__.py`:

```python
from hatchet.workflows.device_group_execution import child_workflow  # noqa: F401  (test patches wf_run_module.child_workflow)
from hatchet.workflows.workflow_run.fan_out_dispatch import (
    _dispatch_children,
    _dispatch_with_approval,
    _parse_fan_out_dispatch,
)
```

*Verification:* `test_wait_and_run_dispatch.py`:
- `from hatchet.workflows.workflow_run import _dispatch_children` → re-export ✓
- `from hatchet.workflows import workflow_run as wf_run_module` then
  `patch.object(wf_run_module.child_workflow, "aio_run", child_run)` → the
  `__init__` re-export of `child_workflow` keeps `wf_run_module.child_workflow`
  resolving to the **same object** that `fan_out_dispatch._run_groups` calls
  (both are `hatchet.workflows.device_group_execution.child_workflow`), so
  patching its `.aio_run` attribute still takes effect ✓
- `patch("core.database.SessionLocal", …)` → `_dispatch_with_approval` still
  does `from core.database import SessionLocal` lazily ✓

#### 2e. Extract `phase1.py`; `__init__.py` becomes wiring only

Move `_maybe_debug_pause_before_node`, `_fan_out_context_if_requested`,
`_run_steps_until_fan_out_or_done`, `_debug_pause_before_fan_out`,
`_phase1_run_or_early_finish`.

**Code before** (`__init__.py`, lines ~381–429):

```python
async def execute_steps(input: WorkflowRunInput, ctx: DurableContext) -> dict:
    logger.info("Executing steps for run_id=%s", input.run_id)
    from core.database import SessionLocal
    from repositories.run_repository import RunRepository
    from repositories.workflow_repository import WorkflowRepository
    from services.execution.step_runner import StepRunner

    early = await _phase1_run_or_early_finish(
        run_id=input.run_id, ctx=ctx, SessionLocal=SessionLocal,
        RunRepository=RunRepository, WorkflowRepository=WorkflowRepository,
        StepRunner=StepRunner,
    )
    if isinstance(early, dict):
        return early
    run_uuid, signal, canvas_nodes, canvas_edges = early
    ...
    child_results = await _dispatch_children(signal, input.run_id, ctx=ctx,
        run_uuid=run_uuid, canvas_nodes=canvas_nodes, canvas_edges=canvas_edges)
    final_status = await _finalize_fan_out_parent(run_id=input.run_id, signal=signal, ...)
    return {"run_id": input.run_id, "status": final_status}
```

**Code after** — `hatchet/workflows/workflow_run/__init__.py` (final shape,
~95 lines):

```python
"""Hatchet `WorkflowExecution` workflow: prepare → execute_steps.

Split into a package (2026-09): task wiring + registration live here; the
per-phase implementation lives in sibling modules —
  phase1.py           phase-1 topological walk, debug stepping, early finish
  fan_out_dispatch.py  phase-2 child dispatch (+ Wait & Run batching)
  batch_approval.py    Wait & Run approval-state + gate helpers
  aggregation.py       phase-3/4 child-result merge, persist, post-join resume

Every phase function is the same plain async function it was before the split
(no behaviour change); `build_workflow_execution` / `workflow` are unchanged
so `from hatchet.workflows.workflow_run import workflow as workflow_execution`
keeps working for hatchet/worker.py, dynamic_worker.py, dispatch.py,
scheduled_trigger.py.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from hatchet_sdk import Context, DurableContext
from pydantic import BaseModel

from hatchet.client import hatchet
# re-exports — keep import paths stable for callers & tests
from hatchet.workflows.device_group_execution import child_workflow  # noqa: F401
from hatchet.workflows.workflow_run.aggregation import (  # noqa: F401
    _aggregate_and_persist,
    _finalize_fan_out_parent,
)
from hatchet.workflows.workflow_run.fan_out_dispatch import _dispatch_children  # noqa: F401
from hatchet.workflows.workflow_run.phase1 import (  # noqa: F401
    _phase1_run_or_early_finish,
    _run_steps_until_fan_out_or_done,
)

if TYPE_CHECKING:
    from hatchet_sdk.runnables.workflow import Workflow as HatchetWorkflow

logger = logging.getLogger(__name__)


class WorkflowRunInput(BaseModel):
    run_id: int


async def prepare(input: WorkflowRunInput, ctx: Context) -> dict:
    # ... verbatim ...


async def execute_steps(input: WorkflowRunInput, ctx: DurableContext) -> dict:
    # ... verbatim (still does the lazy imports and passes them into
    #     _phase1_run_or_early_finish / _finalize_fan_out_parent) ...


def build_workflow_execution(*, name: str, concurrency: int | None = None) -> HatchetWorkflow[WorkflowRunInput]:
    # ... verbatim ...


workflow = build_workflow_execution(name="WorkflowExecution")
```

`phase1.py` holds the five moved functions verbatim. `_phase1_run_or_early_finish`
keeps its injected-parameter signature.

*Verification:*
- `test_step_runner_funnel.py`, `test_debug_mode_stepping.py` import
  `_run_steps_until_fan_out_or_done` from `hatchet.workflows.workflow_run` →
  re-export ✓
- `python -c "import hatchet.worker; import hatchet.dynamic_worker"` ✓
- registration snapshot test (§6.3) ✓

---

### Phase 3 — OUT OF SCOPE for this work (R9)

**Not part of this refactor. Listed only so the ideas are recorded and
explicitly deferred.** This effort ships Phases 0–2 and stops. Phase 3 is a
separate proposal, separately reviewed, and item 1 may never be worth doing.

1. **Unify the four topological walk loops — behaviour rewrite, not cleanup.**
   `StepRunner.execute_all`, `StepRunner.resume_after_join`,
   `subgraph.run_subgraph`, and `phase1._run_steps_until_fan_out_or_done`
   *look* similar but are **deliberately not the same skeleton**:
   - `execute_all` — persists `WorkflowStepResult`; on a raised executor it
     hard-stops and blanket-skips the rest; can return a `FanOutSignal`.
   - `resume_after_join` — persists; seeds `step_outcomes` from merged child
     outcomes; only walks `post_join_ids`.
   - `run_subgraph` — does **not** persist; filters to `allowed_node_ids`;
     records per-node errors into a dict and keeps going.
   - `_run_steps_until_fan_out_or_done` — injects a durable debug-pause
     `aio_wait_for_event` before each node; reloads `run` after resume; can
     return a fan-out context.
   A shared `_walk(...)` with four behaviour flags is exactly where a silent
   skip / wrong-status / missed-fan-out bug would hide. If ever attempted, it
   needs its own design doc and its own review.
2. **Drop the injected-parameter pattern** in `phase1` / `aggregation`. Low
   value, and a fresh patch-target minefield (`SessionLocal`, `RunRepository`,
   `StepRunner` are passed in partly so tests can substitute them).
3. **Migrate tests to submodule paths and delete the delegating shims.** The
   shims *are* the compatibility contract. Years-later, if ever.

---

## 6. Testing strategy — can we prove the refactor is safe?

**Yes**, but only if Phase 0 is done properly — the existing suite alone is
**not** enough (see the gap table below). Four layers, in order of value.

### 6.1 The existing suite — a strong gate for *some* paths, blind on others

Every phase is a pure move with re-exports + delegators, so all current tests
must pass unchanged **except** the one patch-target rebind in §2.4. What the
suite actually covers:

```
test_step_runner_funnel.py                 funnel splice + e2e via _run_steps_until_fan_out_or_done   ✅ strong
test_step_runner_disabled_steps.py         disabled-step bypass (12 cases) + build_execution_plan     ✅ strong
test_step_runner_blocked_by_failure.py     _blocked_by_upstream_failure (unit + integration)          ✅ strong
test_step_runner_errors.py                 classify_step_exception + _execute_and_persist_node error   ✅ strong
test_step_runner_serialize_outcomes.py     _serialize_outcomes redaction + no-mutation                ✅ strong
test_step_runner_device_sessions.py        _execute_step guards + DeviceSessionPool suspend/close      ✅ strong
test_canvas_decoration_execution_plan.py   executable filtering                                        ✅ strong
test_execution_graph.py                    topological_order / downstream / join detection             ✅ strong
test_debug_mode_stepping.py                per-node debug pause/resume, atomic fan-out step            ✅ strong
test_aggregate_and_persist_final.py        _aggregate_and_persist final vs non-final                   ✅ strong
test_wait_and_run_dispatch.py              batch-approval gating in _dispatch_children                 ✅ strong
test_hatchet_workers.py                    worker import / registration                                ✅ strong
```

**Uncovered by any unit test today (R5) — the paths this split moves:**

| Moved code | Unit test today |
|---|---|
| `execute_subgraph` / `run_subgraph` (1e) | **none** — `test_fan_out_metadata.py` tests `build_fan_out_metadata`, a different function |
| `resume_after_join` (moves to `runner.py` in 1d) | **none** |
| `_finalize_fan_out_parent` (2b) | **none** |
| `execute_steps` glue: phase1 → dispatch → finalize (2e) | **none** |
| `execute_all` | integration only (`test_workflow_run_end_to_end.py`, linear, no fan-out); production uses `_run_steps_until_fan_out_or_done` instead |

→ **Phase 0's `fanout_no_join` / `fanout_with_join` / post-join-resume
fingerprints are mandatory, not illustrative.** They are the only net around
1d/1e/2b. If they cannot be written to genuinely exercise `execute_subgraph`
and `resume_after_join` (real stubbed executors, real `WorkflowStepResult`
assertions), the split of those functions should not proceed.

### 6.2 New characterization ("golden fingerprint") test — write in Phase 0

New file `backend/tests/unit/test_execution_characterization.py`. Table-driven:
run representative canvas shapes through the **real production entrypoints**
with `StepRunner._execute_step` and `child_workflow.aio_run` stubbed, and
assert a full structured fingerprint against a committed JSON fixture.

Shapes to cover:

| id | shape | entrypoint |
|---|---|---|
| `linear_3` | A→B→C all succeed | `_run_steps_until_fan_out_or_done` (normal mode) |
| `branch_failure` | A→B(fail)→C, A→D via `failure` handle | `_run_steps_until_fan_out_or_done` |
| `funnel_to_sink` | two failing branches → funnel → notify | `_run_steps_until_fan_out_or_done` |
| `disabled_chain` | A→X(off)→Y(off)→B collapses to A→B | `StepRunner.execute_all` |
| `blocked_upstream` | inventory→cmd(all devices fail)→downstream device step | `StepRunner.execute_all` |
| `resume_after_join_only` | call `resume_after_join` directly with hand-built merged outcomes over `join → store → notify` | `StepRunner.resume_after_join` |
| `fanout_no_join` | inventory fan-out, no fan-in | `execute_subgraph` + `_aggregate_and_persist` |
| `fanout_with_join` | inventory fan-out → fan-in → store | `execute_subgraph` + `_aggregate_and_persist` + `resume_after_join` |
| `fanout_child_error` | one child branch raises in a node → parent folds `error_message`/`category`/`error_id` | `execute_subgraph` + `_aggregate_and_persist` |
| `wait_and_run_2_batches` | 4 device groups, batch_size 2, first_batch_auto | `_dispatch_children` (stubbed `aio_run`) |

`resume_after_join_only`, `fanout_no_join`, `fanout_with_join`,
`fanout_child_error` are the cases that give `execute_subgraph` /
`resume_after_join` their **first** test coverage (R5) — do not treat them as
optional extras.

Fingerprint captured per case (all JSON-serialisable):

```python
{
  "executed_node_order": ["inv", "a", "b"],           # order _execute_step was called
  "return_value": "failed",                            # or {"fan_out": {...}} / bool
  "step_results": {
    "inv": {"status": "success", "error_category": None,
            "output_outcomes": ["success"], "output_device_ids": {"success": ["d1","d2"]}},
    "a":   {"status": "failed", "error_category": "execution", "error_message_prefix": "boom",
            "output_outcomes": [], "output_device_ids": {}},
    ...
  },
  "run_status_transitions": ["running", "paused", "running", "failed"],
  "approval_state_snapshots": [ {...}, {...} ],         # for wait_and_run case
  "fan_out_signal": {"inventory_node_id": "inv", "mode": "per_device",
                     "join_node_id": "join", "step_outcome_nodes": ["inv"]},
}
```

Test body:

```python
import json, pathlib
FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "execution_fingerprints.json"

@pytest.mark.parametrize("case_id", ALL_CASE_IDS)
def test_execution_fingerprint_unchanged(case_id):
    expected = json.loads(FIXTURE.read_text())[case_id]
    actual = run_case_and_capture_fingerprint(case_id)   # drives real entrypoint
    assert actual == expected
```

Generate the fixture **once, on `main` before any refactoring**, via a
`--generate-fingerprints` flag or a one-off script; commit it in the Phase 0
commit. From then on the fixture is frozen — every phase re-runs this file
unchanged. A diff = a behaviour change = stop.

Fixture-stability rules (R-review §3.7): drive the **real** entrypoints, never
a reimplementation of the walk; strip `uuid4` `error_id`s and timestamps from
the fingerprint (keep `error_id: "<present>"` / `None`); sort every list
(`executed_node_order` is call order and stays as-is, but
`output_device_ids[outcome]`, `output_outcomes`, dict-key iterations get
`sorted(...)`) so the JSON never flakes on ordering.

This is the strongest guarantee: it pins observable execution semantics
(ordering, persisted rows, status machine, fan-out payload) independent of
internal structure.

### 6.3 Import-surface + registration guard — write in Phase 0

New file `backend/tests/unit/test_refactor_import_surface.py`:

```python
def test_step_runner_public_symbols_importable():
    from services.execution.step_runner import (
        StepRunner, FanOutSignal, classify_step_exception,
    )
    for name in ("_resolve_funnels", "_resolve_disabled_steps",
                 "_blocked_by_upstream_failure", "_serialize_outcomes",
                 "_seed_run_inputs", "_is_executable_node",
                 "build_execution_plan", "load_execution_graph",
                 "execute_all", "resume_after_join", "execute_subgraph"):
        assert hasattr(StepRunner, name), name

def test_workflow_run_public_symbols_importable():
    from hatchet.workflows import workflow_run as m
    for name in ("WorkflowRunInput", "prepare", "execute_steps",
                 "build_workflow_execution", "workflow",
                 "_run_steps_until_fan_out_or_done", "_aggregate_and_persist",
                 "_dispatch_children", "child_workflow"):
        assert hasattr(m, name), name

def test_hatchet_registration_snapshot():
    # hatchet-sdk 1.38.1: Workflow has .name and .tasks; task-config fields are
    # .execution_timeout and .parents. Assert the real values, not a guessed shape.
    from hatchet.workflows.workflow_run import workflow
    assert workflow.name == "WorkflowExecution"
    tasks = {t.name: t for t in workflow.tasks}
    assert set(tasks) == {"prepare", "execute_steps"}
    assert tasks["execute_steps"].parents == [tasks["prepare"]]
    assert tasks["prepare"].execution_timeout == timedelta(seconds=30)
    assert tasks["execute_steps"].execution_timeout == timedelta(hours=24)

def test_workers_import_cleanly():
    # needs the HATCHET_CLIENT_* env the suite already sets for
    # test_hatchet_workers.py (hatchet/client.py builds Hatchet() at import)
    import importlib
    for mod in ("hatchet.worker", "hatchet.dynamic_worker",
                "hatchet.workflows.dispatch",
                "hatchet.workflows.scheduled_trigger"):
        importlib.import_module(mod)
```

### 6.4 Differential test for extracted pure functions — Phase 1c only

Hypothesis is **not** a project dependency (R7) — use a **fixed corpus**. While
`graph_resolution` is being extracted, temporarily keep the old static-method
body under a `_legacy_` name and assert equivalence over a hand-written list of
~30 graph shapes (linear, branch, funnel×{0,1,2,chain-error}, disabled
{parked, bypass, chain, branch-success-only, cycle}, mixed decoration nodes):

```python
GRAPH_CORPUS: list[tuple[list[dict], list[dict]]] = [ ... ~30 (nodes, edges) ... ]

@pytest.mark.parametrize("nodes,edges", GRAPH_CORPUS)
def test_resolve_funnels_matches_legacy(nodes, edges):
    assert resolve_funnels(nodes, edges) == StepRunner._legacy_resolve_funnels(nodes, edges)
```

Delete both the `_legacy_` bodies and this test once 1c lands green. (The
existing `test_step_runner_funnel.py` / `test_step_runner_disabled_steps.py`
already lock the behaviour long-term; this is only a transition check.)

### 6.5 Non-test gates (run every phase)

```
python -m pytest --cov=services/execution/step_runner --cov=hatchet/workflows/workflow_run \
                 --cov-report=term-missing        # line coverage must not drop
python scripts/check_asyncio_run.py
python scripts/check_http_500_leaks.py
python scripts/check_router_repositories.py
python scripts/check_text_sql.py
ruff check services/execution/step_runner hatchet/workflows/workflow_run
pyright services/execution/step_runner hatchet/workflows/workflow_run
python -c "import hatchet.worker"                 # smoke: static Hatchet registration
```

Optional, if a disposable Hatchet dev stack is available: run one real
end-to-end workflow (linear) and one fan-out workflow through
`scripts/run_worker_dev.py` before merging Phase 2.

---

## 7. Rollback

Each phase is one commit and behaviour-neutral, so `git revert <sha>` restores
the previous structure with no data/migration implications. If a problem is
found after several phases, revert from the top — later phases don't depend on
earlier ones being *split further*, only on the package existing (Phase 1a /
2a).

---

## 8. Review checklist (fill in during review)

Structural:
- [ ] §2.1 importer list is complete (re-grep before starting) — incl.
      `tests/integration/test_workflow_run_end_to_end.py`
- [ ] §2.2 test-symbol list is complete (re-grep before starting) — incl. the
      four `services.execution.step_runner.<guard>` patch targets
- [ ] Package split introduces **no** new module-level DB / engine imports
- [ ] All lazy in-function imports preserved verbatim (`SessionLocal`,
      `StepRunner`, `FanOutSignal`, `STEP_REGISTRY`, repositories)
- [ ] No sibling module imports through the package `__init__` (R4) — full
      paths / `import … as` only
- [ ] `child_workflow` object identity preserved for `patch.object` in
      `test_wait_and_run_dispatch.py`; `wf_run_module.child_workflow` still resolves
- [ ] `_plugin_registry_service` stays a single `@lru_cache` function
- [ ] Hatchet registration snapshot (name, tasks, parents, timeouts, on_events)
      unchanged
- [ ] `runner.py` left at ~600 lines — **not** split further (R6)

Ordering / correctness:
- [ ] Phase 1: class moves to `runner.py` (1d) **before** `subgraph.py` (1e) (R1)
- [ ] `mkdir -p` precedes every `git mv … /__init__.py` (R3)
- [ ] Phase 1d commit includes the `test_step_runner_device_sessions.py`
      patch-target rebind (`…step_runner.<guard>` → `…step_runner.runner.<guard>`)
      and nothing else in that file changes (R2)

Testing:
- [ ] Phase 0 fingerprint fixture generated on clean `main`, timestamps/uuids
      stripped, lists sorted (R-review §3.7)
- [ ] Phase 0 includes real `execute_subgraph` + `resume_after_join` +
      `_finalize_fan_out_parent` fingerprints (R5) — these functions have **no**
      unit test today
- [ ] §6.4 differential test uses a fixed corpus, not Hypothesis (R7)
- [ ] Every phase: suite green (only the §2.4 patch rebind excepted), unchanged
      test count otherwise, coverage on both modules not lower

Scope:
- [ ] Phase 3 explicitly **out of scope** — not "optional in this PR" (R9)

---

## 9. Outcome (size after Phases 1–2)

| Module | ~lines |
|---|---|
| `step_runner/__init__.py` | 40 |
| `step_runner/signals.py` | 55 |
| `step_runner/graph_resolution.py` | 240 |
| `step_runner/subgraph.py` | 190 |
| `step_runner/runner.py` | **~600** |
| `workflow_run/__init__.py` | 95 |
| `workflow_run/phase1.py` | 185 |
| `workflow_run/fan_out_dispatch.py` | 280 |
| `workflow_run/batch_approval.py` | 135 |
| `workflow_run/aggregation.py` | 155 |

All under the 800 ceiling (largest `runner.py` ≈ 600 — see R6, do not chase it
lower). No public API change. No behaviour change. Existing suite unchanged
apart from one patch-target rebind in `test_step_runner_device_sessions.py`
(§2.4); two new guard test files + one fingerprint fixture added in Phase 0.

Phase 3 (unify the four walk loops, drop injected params, delete shims) is a
**separate future proposal** and may never be worth the risk — see §5 Phase 3.
