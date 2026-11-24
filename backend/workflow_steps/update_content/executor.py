"""Executor for the update-content step.

Reads a device's running or startup config, applies an ordered list of regex
search/replace rules to the text (bulk `re.sub`-style, not single-match extraction),
and stores the result as a new `updated_content` artifact so downstream steps
(store-artifact, and future upload/verify steps) can consume it via
`workflow_steps/common/content_resolver.py`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import (
    ArtifactRef,
    DeviceContext,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.workflow_context.attribute_regex import (
    RegexFlagsConfig,
    apply_regex_content_replace,
    compile_pattern,
)
from workflow_steps.common.content_resolver import parse_content_source
from workflow_steps.common.content_step import StoredContent, run_content_step
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.step_flags import parse_bool_flag

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "update-content"
_SUPPORTED_SOURCES = frozenset({"running_config", "startup_config"})


@dataclass(frozen=True)
class _ReplaceRule:
    pattern: str
    replacement: str
    regex_flags: RegexFlagsConfig
    replace_all: bool


@dataclass(frozen=True)
class _ParsedUpdateContentConfig:
    content_source: str
    rules: list[_ReplaceRule]
    fail_if_no_match: bool = False


class _NoRuleMatched(ValueError):  # noqa: N818 - internal signal, mapped to a device error code
    """Every rule matched zero times on this device."""


def _parse_rules(config: dict[str, Any]) -> list[_ReplaceRule]:
    raw = config.get("replace_rules")
    if not raw:
        raise ValueError("update-content: at least one rule in replace_rules is required")
    if not isinstance(raw, list):
        raise ValueError("update-content: replace_rules must be a list")

    rules: list[_ReplaceRule] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"update-content: replace_rules[{i}] must be a dict")
        pattern = str(item.get("pattern") or "").strip()
        if not pattern:
            raise ValueError(f"update-content: replace_rules[{i}].pattern is required")
        regex_flags = RegexFlagsConfig.from_mapping(item.get("regex_flags"))
        try:
            compile_pattern(pattern, regex_flags)
        except ValueError as exc:
            raise ValueError(f"update-content: replace_rules[{i}].{exc}") from exc
        rules.append(
            _ReplaceRule(
                pattern=pattern,
                replacement=str(item.get("replacement") or ""),
                regex_flags=regex_flags,
                replace_all=parse_bool_flag(
                    item, "replace_all", default=True, step_id=f"{_STEP_ID} replace_rules[{i}]"
                ),
            )
        )
    return rules


def _parse_update_content_config(config: dict[str, Any]) -> _ParsedUpdateContentConfig:
    return _ParsedUpdateContentConfig(
        content_source=parse_content_source(
            config, step_id=_STEP_ID, default="running_config", allowed=_SUPPORTED_SOURCES
        ),
        rules=_parse_rules(config),
        fail_if_no_match=parse_bool_flag(config, "fail_if_no_match", default=False),
    )


def _source_ref(device: DeviceContext, content_source: str) -> ArtifactRef | None:
    if content_source == "running_config":
        return device.running_config_ref
    return device.startup_config_ref


def _apply_rules_to_text(text: str, rules: list[_ReplaceRule]) -> tuple[str, list[int]]:
    match_counts: list[int] = []
    current = text
    for rule in rules:
        current, match_count = apply_regex_content_replace(
            source_text=current,
            pattern=rule.pattern,
            replacement=rule.replacement,
            flags=rule.regex_flags,
            replace_all=rule.replace_all,
        )
        match_counts.append(match_count)
    return current, match_counts


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    parsed = _parse_update_content_config(config)
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    logger.info(
        "update-content started run_id=%s node_id=%s devices=%d content_source=%s rules=%d",
        log_run_id(run),
        node_id,
        len(context.devices),
        parsed.content_source,
        len(parsed.rules),
    )

    async def transform(device_id: str, device: DeviceContext) -> StoredContent:
        source_ref = _source_ref(device, parsed.content_source)
        if source_ref is None:
            raise ValueError(
                f"{parsed.content_source} is not available on this device — add a "
                "Get Configs step upstream of update-content"
            )
        raw_content = await artifact_service.resolve(source_ref)
        # Off the event loop: re.sub over a multi-megabyte config would stall every other device.
        updated_text, match_counts = await asyncio.to_thread(
            _apply_rules_to_text, raw_content, parsed.rules
        )
        if parsed.fail_if_no_match and not any(match_counts):
            # A typo'd pattern would otherwise let a later upload step push the unchanged config.
            raise _NoRuleMatched("no replace rule matched anything in this device's content")
        return StoredContent(
            text=updated_text,
            media_type=source_ref.media_type,
            entry={"match_counts": match_counts},
        )

    return await run_content_step(
        context,
        step_id=_STEP_ID,
        node_id=node_id,
        kind="updated_content",
        transform=transform,
        artifact_service=artifact_service,
        metadata_prefix="update_content",
        code_overrides={_NoRuleMatched: "no_rule_matched"},
    )
