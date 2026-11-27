"""W2-09: the shim-client half of the pyATS batching lives in ``services/pyats/batch.py``.

``workflow_steps/common/pyats_batch.py`` keeps only the step glue (resolving the sources of the
devices, validating and grouping them by source); chunking, the concurrency limit, the job call
and the reading of a per-device shim result are pyATS client orchestration that a router or a
script could use too.
"""

from __future__ import annotations

import ast
import inspect

import services.pyats.batch as batch
import workflow_steps.common.pyats_batch as step_glue

_CLIENT_NAMES = (
    "DEFAULT_CHUNK_SIZE",
    "BASE_TIMEOUT_SECONDS",
    "PER_DEVICE_TIMEOUT_SECONDS",
    "MAX_SHIM_TEXT",
    "run_batched",
    "shim_concurrency",
    "shim_device_failure",
)


def test_the_client_half_is_in_services() -> None:
    assert all(hasattr(batch, name) for name in _CLIENT_NAMES)


def test_the_step_glue_keeps_only_the_glue() -> None:
    assert [name for name in (*_CLIENT_NAMES, "_chunk") if hasattr(step_glue, name)] == []
    assert callable(step_glue.resolve_source_credentials)
    assert callable(step_glue.validate_and_group_devices)


def test_the_service_module_does_not_import_the_steps() -> None:
    tree = ast.parse(inspect.getsource(batch))
    modules = [
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    ]
    assert [m for m in modules if m and m.startswith("workflow_steps")] == []
