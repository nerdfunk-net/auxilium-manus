"""Resolve a step-config value that may be either a literal or a pointer at a
run parameter (a workflow ``static_attributes`` entry, supplied per-run /
per-schedule and persisted on ``WorkflowRun.run_inputs``).

Used by every step that lets the operator choose "use this fixed value" vs
"take it from a run parameter" — currently the inventory selector's inventory
and every SSH step's credential. One implementation so the six SSH executors
plus ``get_nautobot_devices`` never drift on the fallback / error wording.
"""

from __future__ import annotations

from typing import Any

_RUN_PARAM = "run_param"


def resolve_config_reference(
    config: dict[str, Any],
    *,
    source_key: str,
    param_key: str,
    literal_key: str,
    run_inputs: dict[str, Any] | None,
) -> str:
    """Return the effective reference string for ``literal_key``.

    - ``config[source_key] == "run_param"`` → look up ``config[param_key]`` (a
      run-parameter name) in ``run_inputs`` and return that value as ``str``.
    - anything else → return ``config[literal_key]`` verbatim.

    Raises ``ValueError`` when the run-param mode is selected but the parameter
    name is blank or absent from ``run_inputs`` (an unresolved reference must
    fail the step, not silently fall back to a stale literal).
    """
    if str(config.get(source_key) or "").strip() != _RUN_PARAM:
        return str(config.get(literal_key) or "").strip()

    param_name = str(config.get(param_key) or "").strip()
    if not param_name:
        raise ValueError(f"{source_key} is 'run_param' but {param_key} is not set")

    inputs = run_inputs or {}
    if param_name not in inputs:
        raise ValueError(
            f"run parameter {param_name!r} is not present in this run's inputs"
        )
    return str(inputs[param_name]).strip()
