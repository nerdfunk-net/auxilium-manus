"""Import-surface + Hatchet-registration guard for the step_runner /
workflow_run package split (doc/refactoring/STEPRUNNER_WORKFLOWRUN.md §6.3).

Every public and test-private symbol that other modules / tests import from
``services.execution.step_runner`` and ``hatchet.workflows.workflow_run`` must
keep resolving from those exact paths after the files become packages. This
file fails loudly the moment a re-export is dropped.
"""

from __future__ import annotations

import importlib
from datetime import timedelta


def test_step_runner_public_symbols_importable() -> None:
    from services.execution.step_runner import (
        FanOutSignal,
        StepRunner,
        classify_step_exception,
    )

    assert FanOutSignal is not None
    assert callable(classify_step_exception)

    for name in (
        "_resolve_funnels",
        "_resolve_disabled_steps",
        "_blocked_by_upstream_failure",
        "_serialize_outcomes",
        "_seed_run_inputs",
        "_is_executable_node",
        "build_execution_plan",
        "load_execution_graph",
        "execute_all",
        "resume_after_join",
        "execute_subgraph",
    ):
        assert hasattr(StepRunner, name), name


def test_step_runner_guard_patch_targets_resolve() -> None:
    """test_step_runner_device_sessions.py patches these as string paths."""
    import services.execution.step_runner as m

    for name in (
        "pre_step_guard",
        "post_step_guard",
        "effective_produces",
        "capability_spec_from_plugin",
    ):
        assert hasattr(m, name), name


def test_workflow_run_public_symbols_importable() -> None:
    from hatchet.workflows import workflow_run as m

    for name in (
        "WorkflowRunInput",
        "prepare",
        "execute_steps",
        "build_workflow_execution",
        "workflow",
        "_run_steps_until_fan_out_or_done",
        "_aggregate_and_persist",
        "_dispatch_children",
        "child_workflow",
    ):
        assert hasattr(m, name), name


def test_child_workflow_object_identity_preserved() -> None:
    """test_wait_and_run_dispatch.py does
    ``patch.object(wf_run_module.child_workflow, "aio_run", ...)`` — the object
    exposed at the package root must be the one the dispatch code actually
    calls, i.e. the singleton from device_group_execution.
    """
    from hatchet.workflows import workflow_run as wf_run_module
    from hatchet.workflows.device_group_execution import child_workflow

    assert wf_run_module.child_workflow is child_workflow


def test_hatchet_registration_snapshot() -> None:
    from hatchet.workflows.workflow_run import workflow

    assert workflow.name == "WorkflowExecution"
    tasks = {t.name: t for t in workflow.tasks}
    assert set(tasks) == {"prepare", "execute_steps"}
    assert tasks["execute_steps"].parents == [tasks["prepare"]]
    assert tasks["prepare"].execution_timeout == timedelta(seconds=30)
    assert tasks["execute_steps"].execution_timeout == timedelta(hours=24)


def test_workers_import_cleanly() -> None:
    for mod in (
        "hatchet.worker",
        "hatchet.dynamic_worker",
        "hatchet.workflows.dispatch",
        "hatchet.workflows.scheduled_trigger",
    ):
        importlib.import_module(mod)
