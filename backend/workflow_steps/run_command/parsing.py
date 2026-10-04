"""Config parsing and validation for the run-command step."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from services.network.netmiko.connection import RetryPolicy
from workflow_steps.common.jinja_render import parse_output_key
from workflow_steps.common.read_timeout import parse_read_timeout
from workflow_steps.common.retry_config import parse_retry_backoff_seconds
from workflow_steps.common.step_flags import parse_bool_flag
from workflow_steps.run_command.constants import STEP_ID

_EXECUTION_MODES = {"config_mode", "exec_mode"}


def _default_config() -> dict[str, Any]:
    from workflow_steps.run_command.config import get_config

    return get_config()


def _parse_commands(config: dict[str, Any]) -> list[str]:
    raw = config.get("commands")
    if raw is None:
        raw = _default_config().get("commands", [])
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            raw = []
        else:
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError:
                raw = [line.strip() for line in stripped.splitlines() if line.strip()]
    if not isinstance(raw, list):
        raise ValueError("run-command: commands must be a list of strings")
    commands = [str(command).strip() for command in raw if str(command).strip()]
    if not commands:
        raise ValueError("run-command: at least one command is required")
    return commands


_PARSER_MODES = frozenset({"none", "textfsm", "genie"})


def _parse_parser_mode(config: dict[str, Any]) -> str:
    """Which parser (if any) normalizes this step's command output.

    "textfsm" and "genie" are mutually exclusive: whichever is selected, the
    result lands inline at ``parsed.<parsed_output_key>.<command>`` in the same
    ``{"parsed": ..., "error": ...}`` shape (see ``enrich_with_textfsm`` /
    ``enrich_with_genie``), so a downstream step never needs to know which
    parser produced it.

    parser must be "none" whenever execution_mode is "config_mode" or
    auto_confirm_prompts is enabled — see ``_validate_mode_combination``.
    """
    raw = config.get("parser")
    if raw is None:
        raw = _default_config()["parser"]
    mode = str(raw).strip().lower()
    if mode not in _PARSER_MODES:
        raise ValueError(
            f"run-command: parser must be one of {sorted(_PARSER_MODES)}, got {mode!r}"
        )
    return mode


def _parse_execution_mode(config: dict[str, Any]) -> str:
    mode = str(config.get("execution_mode") or _default_config()["execution_mode"]).strip().lower()
    if mode not in _EXECUTION_MODES:
        raise ValueError(f"run-command: execution_mode must be one of {sorted(_EXECUTION_MODES)}")
    return mode


def _validate_mode_combination(
    *, parser_mode: str, execution_mode: str, auto_confirm_prompts: bool
) -> None:
    if parser_mode != "none" and (execution_mode == "config_mode" or auto_confirm_prompts):
        raise ValueError(
            "run-command: parser must be 'none' when execution_mode is 'config_mode' "
            "or auto_confirm_prompts is enabled"
        )


def _validate_write_config_scope(
    *, execution_mode: str, write_config_after_execution: bool
) -> None:
    if write_config_after_execution and execution_mode != "config_mode":
        raise ValueError(
            "run-command: write_config_after_execution requires execution_mode 'config_mode'"
        )


@dataclass(frozen=True)
class ParsedRunCommandConfig:
    credential_reference: str
    commands: list[str]
    parser_mode: str
    network_driver_override: str | None
    pyats_source_id: str
    parsed_output_key: str
    execution_mode: str
    write_config_after_execution: bool
    read_timeout: int
    auto_confirm_prompts: bool
    dry_run: bool
    retry: RetryPolicy


def parse_run_command_config(config: dict[str, Any]) -> ParsedRunCommandConfig:
    commands = _parse_commands(config)
    parser_mode = _parse_parser_mode(config)
    execution_mode = _parse_execution_mode(config)
    auto_confirm_prompts = parse_bool_flag(config, "auto_confirm_prompts")
    write_config_after_execution = parse_bool_flag(config, "write_config_after_execution")
    dry_run = parse_bool_flag(config, "dry_run")

    _validate_mode_combination(
        parser_mode=parser_mode,
        execution_mode=execution_mode,
        auto_confirm_prompts=auto_confirm_prompts,
    )
    _validate_write_config_scope(
        execution_mode=execution_mode,
        write_config_after_execution=write_config_after_execution,
    )

    pyats_source_id = str(config.get("pyats_source_id") or "").strip()
    if parser_mode == "genie" and not pyats_source_id:
        raise ValueError("run-command: pyats_source_id is required when parser is 'genie'")

    parsed_output_key = ""
    if parser_mode != "none":
        parsed_output_key = parse_output_key(
            config.get("parsed_output_key") or _default_config()["parsed_output_key"]
        )

    return ParsedRunCommandConfig(
        credential_reference="",
        commands=commands,
        parser_mode=parser_mode,
        network_driver_override=str(config.get("network_driver_override") or "").strip() or None,
        pyats_source_id=pyats_source_id,
        parsed_output_key=parsed_output_key,
        execution_mode=execution_mode,
        write_config_after_execution=write_config_after_execution,
        read_timeout=parse_read_timeout(
            config, step_id=STEP_ID, default=_default_config()["read_timeout"]
        ),
        auto_confirm_prompts=auto_confirm_prompts,
        dry_run=dry_run,
        retry=parse_retry_backoff_seconds(config, step_id=STEP_ID),
    )
