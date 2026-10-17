"""Executor for the route-on-attribute control-flow step."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, DeviceError, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.workflow_context.attribute_expression.evaluator import (
    RegexLookup,
    RegexUnavailableError,
    evaluate,
)
from services.workflow_context.attribute_expression.regex_batch import resolve_regex_batch
from services.workflow_context.attribute_expression.route_values import (
    RESERVED_OUTCOMES,
    classify_values,
    outcome_problem,
    raw_values_to_list,
)
from services.workflow_context.attribute_path import (
    AttributeState,
    resolve_device_attribute_state,
)
from workflow_steps.common.partial_outcomes import mark_device_failed
from workflow_steps.route_on_attribute.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_RESERVED_OUTCOMES = RESERVED_OUTCOMES
_STEP_ID = "route-on-attribute"

# Rounds of regex questions before giving up: a pattern or text built from an earlier regex
# result needs one more round per level. Bounded so a cycle of dependent patterns cannot spin.
_MAX_REGEX_PASSES = 4


def _default_config() -> dict[str, Any]:
    return get_config()


def _normalize_value(value: str, *, case_sensitive: bool) -> str:
    return value if case_sensitive else value.casefold()


def _parse_routes(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw_routes = config.get("routes")
    if raw_routes is None:
        raw_routes = _default_config()["routes"]
    if not isinstance(raw_routes, list) or not raw_routes:
        raise ValueError("route-on-attribute: at least one route is required")

    routes: list[dict[str, Any]] = []
    seen_outcomes: set[str] = set()
    for index, raw_route in enumerate(raw_routes):
        if not isinstance(raw_route, dict):
            raise ValueError(f"route-on-attribute: routes[{index}] must be an object")

        outcome = str(raw_route.get("outcome") or "").strip()
        problem = outcome_problem(outcome, seen_outcomes)
        if problem:
            raise ValueError(f"route-on-attribute: routes[{index}].outcome {problem}")
        seen_outcomes.add(outcome)

        try:
            literals, expressions = classify_values(raw_values_to_list(raw_route.get("values")))
        except ValueError as exc:
            raise ValueError(f"route-on-attribute: routes[{index}]: {exc}") from exc

        routes.append({"outcome": outcome, "literals": literals, "expressions": expressions})

    return routes


def _parse_case_sensitive(config: dict[str, Any]) -> bool:
    value = config.get("case_sensitive", _default_config()["case_sensitive"])
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _match_route(
    *,
    route: dict[str, Any],
    device: DeviceContext,
    device_value: str | None,
    attribute_path: str,
    case_sensitive: bool,
    regex: RegexLookup,
    error: DeviceError | None,
) -> bool:
    # Every expression of the route is evaluated (no short-circuit); `and`/`or` evaluate both
    # sides too. The collection loop in `_answer_regex_questions` relies on this to see every
    # regex question of a route, and calls this for every route, not only up to the first hit.
    expression_hits = [
        evaluate(expr, device, default_path=attribute_path, regex=regex, error=error)
        for expr in route["expressions"]
    ]
    if any(expression_hits):
        return True
    if device_value is None or not route["literals"]:
        return False
    wanted = {_normalize_value(v, case_sensitive=case_sensitive) for v in route["literals"]}
    return _normalize_value(device_value, case_sensitive=case_sensitive) in wanted


def _device_inputs(
    device: DeviceContext, attribute_path: str
) -> tuple[DeviceError | None, AttributeState, str | None]:
    latest_error = device.errors[-1] if device.errors else None
    state, resolved = resolve_device_attribute_state(device, attribute_path, error=latest_error)
    return latest_error, state, resolved


async def _answer_regex_questions(
    *,
    devices: dict[str, DeviceContext],
    attribute_path: str,
    routes: list[dict[str, Any]],
    case_sensitive: bool,
) -> dict[tuple[str, str, str], bool | str]:
    """Ask the isolated regex runner every question the routes raise, round by round.

    A round evaluates EVERY route for EVERY device (routing stops at the first hit, collecting
    must not), asking the runner for the questions it has no answer for. Unanswered regexes
    read as False, which can make a predicate such as ``matches(..):not()`` look true; that only
    adds questions, and the next round asks the ones that were hidden. It ends when a round
    raises nothing new.
    """

    def collect(answers: dict[tuple[str, str, str], bool | str]) -> RegexLookup:
        lookup = RegexLookup(results=answers, strict=False)
        for device in devices.values():
            error, _state, resolved = _device_inputs(device, attribute_path)
            for route in routes:
                _match_route(
                    route=route,
                    device=device,
                    device_value=resolved,
                    attribute_path=attribute_path,
                    case_sensitive=case_sensitive,
                    regex=lookup,
                    error=error,
                )
        return lookup

    answers: dict[tuple[str, str, str], bool | str] = {}
    for _ in range(_MAX_REGEX_PASSES):
        lookup = collect(answers)
        if not lookup.pending:
            return answers
        answers = {**answers, **await resolve_regex_batch(lookup.pending)}
    if collect(answers).pending:
        raise ValueError(
            f"route-on-attribute: regular expression results feed into each other more than "
            f"{_MAX_REGEX_PASSES} levels deep"
        )
    return answers


def _route_devices(
    *,
    devices: dict[str, DeviceContext],
    attribute_path: str,
    routes: list[dict[str, Any]],
    default_outcome: str | None,
    case_sensitive: bool,
    regex: RegexLookup,
) -> tuple[dict[str, dict[str, DeviceContext]], dict[str, tuple[str, str]], list[str]]:
    """Return ``(buckets, failures, missing_attribute_device_ids)``.

    ``failures`` maps a device that could not be routed to ``(code, message)``.
    """
    buckets: dict[str, dict[str, DeviceContext]] = {route["outcome"]: {} for route in routes}
    if default_outcome:
        buckets.setdefault(default_outcome, {})

    failures: dict[str, tuple[str, str]] = {}
    missing_attribute_device_ids: list[str] = []

    for device_id, device in devices.items():
        latest_error, state, resolved = _device_inputs(device, attribute_path)
        if state == AttributeState.ABSENT:
            missing_attribute_device_ids.append(device_id)

        matched_outcome: str | None = None
        try:
            for route in routes:
                if _match_route(
                    route=route,
                    device=device,
                    device_value=resolved,
                    attribute_path=attribute_path,
                    case_sensitive=case_sensitive,
                    regex=regex,
                    error=latest_error,
                ):
                    matched_outcome = route["outcome"]
                    break
        except RegexUnavailableError as exc:
            failures[device_id] = (exc.code, exc.message)
            continue

        if matched_outcome is not None:
            buckets[matched_outcome][device_id] = device
        elif default_outcome:
            buckets[default_outcome][device_id] = device
        else:
            failures[device_id] = (
                "no_route_matched",
                "the attribute value matched no route and no default outcome is set",
            )

    return buckets, failures, missing_attribute_device_ids


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del run, artifact_service

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    logger.info("route-on-attribute started run_id=%s node_id=%s", context.run_id, node_id)

    attribute_path = str(
        config.get("attribute_path") or _default_config()["attribute_path"]
    ).strip()
    if not attribute_path:
        raise ValueError("route-on-attribute: attribute_path is required")

    routes = _parse_routes(config)
    case_sensitive = _parse_case_sensitive(config)
    default_outcome = str(config.get("default_outcome") or "").strip() or None
    if default_outcome in _RESERVED_OUTCOMES:
        raise ValueError(f"route-on-attribute: default_outcome {default_outcome!r} is reserved")

    # matches()/find() run in the isolated regex runner; answer all of them up front, then route.
    answers = await _answer_regex_questions(
        devices=context.devices,
        attribute_path=attribute_path,
        routes=routes,
        case_sensitive=case_sensitive,
    )
    buckets, route_failures, missing_attribute_device_ids = _route_devices(
        devices=context.devices,
        attribute_path=attribute_path,
        routes=routes,
        default_outcome=default_outcome,
        case_sensitive=case_sensitive,
        regex=RegexLookup(results=answers),
    )

    # A device that cannot be routed (no route matched and no default, or one of its regexes
    # could not be evaluated) fails alone: it must not hard-stop every other device and branch
    # (C6-04).
    unmatched = {
        device_id: mark_device_failed(
            context.devices[device_id],
            node_id=node_id,
            step_id=_STEP_ID,
            code=code,
            message=message,
        )
        for device_id, (code, message) in route_failures.items()
    }

    outcome_names = [route["outcome"] for route in routes]
    if default_outcome and default_outcome not in outcome_names:
        outcome_names.append(default_outcome)

    routed_counts = {
        outcome_name: len(buckets.get(outcome_name, {})) for outcome_name in outcome_names
    }
    metadata = {
        **context.metadata,
        f"{node_id}.attribute_path": attribute_path,
        f"{node_id}.routed_counts": routed_counts,
        f"{node_id}.missing_attribute_device_ids": missing_attribute_device_ids,
    }

    logger.info(
        "route-on-attribute finished node_id=%s attribute_path=%s routed_counts=%s",
        node_id,
        attribute_path,
        routed_counts,
    )

    outcomes = [
        StepOutcome(
            name=outcome_name,
            context=context.model_copy(
                update={
                    "devices": dict(buckets.get(outcome_name, {})),
                    "metadata": metadata,
                }
            ),
        )
        for outcome_name in outcome_names
    ]
    if unmatched:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(update={"devices": unmatched, "metadata": metadata}),
                summary=f"{len(unmatched)} device(s) could not be routed",
            )
        )
    return outcomes
