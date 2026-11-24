"""Building blocks the Nautobot update steps share (W5-03, W5-04, W5-06).

``update-nautobot-vlan`` (Update VLAN), ``update-nautobot-prefix`` (Update IP Prefix),
``update-nautobot-ip`` (Update IP) and ``get-next-free-ip`` (Get Next Free IP) resolve ``{path}``
expressions per device, look names up to ids once per distinct value and report ``success`` /
``failure`` with counts. The pieces that were copied between them live here:

- ``resolve_fields`` / ``resolve_field``: an expression becomes text; a value taken from a secret is
  refused and an expression that resolves to nothing fails the device. The values end up in a
  Nautobot request and in error text, so a secret is never copied.
- the three failure records and ``failed`` (a device failure with a ``FailureInfo``);
- ``NameLookups``: name -> id lookups, each distinct name asked of Nautobot once;
- ``build_update_outcomes``: the ``success`` / ``failure`` outcomes with ``updated`` / ``unchanged``
  / ``failed`` counts under ``<node_id>.<counts_key>``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from models.failure import FailureInfo
from models.workflow_context import DeviceContext, DeviceError, StepOutcome, WorkflowContext
from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER
from workflow_steps.common.partial_outcomes import fail_device_with_error
from workflow_steps.common.value_expression import resolve_update_field_expression

OUTCOME_NAMES = ("success", "failure")

# (code, message, failure): why one device cannot be updated.
PlanError = tuple[str, str, FailureInfo]


def not_found_failure() -> FailureInfo:
    return FailureInfo(phase="api", kind="not_found", hint="check_request")


def bad_request_failure() -> FailureInfo:
    return FailureInfo(phase="config", kind="bad_request", hint="check_request")


def ambiguous_failure() -> FailureInfo:
    return FailureInfo(phase="api", kind="ambiguous_match", hint="check_request")


def failed(
    step_id: str,
    device: DeviceContext,
    *,
    node_id: str,
    code: str,
    message: str,
    failure: FailureInfo,
) -> DeviceContext:
    """``device`` marked failed with one error that always carries its ``FailureInfo``."""
    error = DeviceError(
        node_id=node_id, step_id=step_id, code=code, message=message, failure=failure
    )
    return fail_device_with_error(device, error)


def resolve_field(device: DeviceContext, run_id: str, field: str, raw: str) -> str | PlanError:
    """One expression as stripped text, or the plan error that fails the device.

    ``reveal_secrets=False``: the value is copied into a Nautobot request and into error text, so
    one taken from a secret is refused. The message repeats the configured expression, never the
    value.
    """
    value = resolve_update_field_expression(
        device=device, field_key=field, raw_value=raw, run_id=run_id, reveal_secrets=False
    )
    if value == REDACTED_PLACEHOLDER:
        return (
            f"{field}_is_secret",
            f"{field} expression {raw!r} points to a secret, which this step does not copy",
            bad_request_failure(),
        )
    if value is None:
        return (
            f"{field}_unresolved",
            f"{field} expression {raw!r} resolved to nothing",
            bad_request_failure(),
        )
    return value.strip()


def resolve_fields(
    device: DeviceContext, run_id: str, pairs: tuple[tuple[str, str], ...]
) -> dict[str, str] | PlanError:
    """Resolve ``(field, expression)`` pairs for one device; an empty expression is skipped."""
    resolved: dict[str, str] = {}
    for field, raw in pairs:
        if not raw:
            continue
        value = resolve_field(device, run_id, field, raw)
        if isinstance(value, tuple):
            return value
        resolved[field] = value
    return resolved


Resolver = Callable[[Any, str], Awaitable[str]]


class NameLookups:
    """Name -> id lookups, each distinct ``(kind, name)`` asked of Nautobot once per execution.

    ``table`` maps a kind to ``(error code when a ValueError says "not found", resolver)``. A
    failed lookup is cached as well, so a missing name is not asked for again.
    """

    def __init__(self, common: Any, table: Mapping[str, tuple[str, Resolver]]) -> None:
        self._common = common
        self._table = table
        self._cache: dict[tuple[str, str], str | Exception] = {}

    async def get(self, kind: str, name: str) -> str | tuple[str, Exception]:
        """The id, or ``(error code, exception)`` when the lookup failed."""
        key = (kind, name)
        if key not in self._cache:
            try:
                self._cache[key] = await self._table[kind][1](self._common, name)
            except Exception as exc:
                self._cache[key] = exc
        found = self._cache[key]
        if isinstance(found, Exception):
            return self._table[kind][0], found
        return found


def build_update_outcomes(
    *,
    context: WorkflowContext,
    node_id: str,
    buckets: dict[str, dict[str, DeviceContext]],
    updated: int,
    counts_key: str,
) -> list[StepOutcome]:
    """The two outcomes; the counts go under ``<node_id>.<counts_key>`` in the metadata."""
    counts = {
        "updated": updated,
        "unchanged": len(buckets["success"]) - updated,
        "failed": len(buckets["failure"]),
    }
    metadata = {**context.metadata, f"{node_id}.{counts_key}": counts}
    return [
        StepOutcome(
            name=name,
            context=context.model_copy(
                update={"devices": dict(buckets[name]), "metadata": metadata}
            ),
        )
        for name in OUTCOME_NAMES
    ]
