"""workflow_steps.run_command.parsing: config parsing and validation."""

from __future__ import annotations

import pytest

from workflow_steps.run_command.parsing import parse_run_command_config


def _parse(**config):
    return parse_run_command_config(config)


def test_defaults() -> None:
    parsed = _parse()

    assert parsed.commands == ["show version"]
    assert parsed.parser_mode == "none"
    assert parsed.execution_mode == "exec_mode"
    assert parsed.parsed_output_key == ""
    assert parsed.write_config_after_execution is False
    assert parsed.dry_run is False


def test_commands_as_json_string() -> None:
    assert _parse(commands='["show ip int brief", "show clock"]').commands == [
        "show ip int brief",
        "show clock",
    ]


def test_commands_as_newline_string_skips_blank_lines() -> None:
    assert _parse(commands="show ip int brief\n\n  show clock  \n").commands == [
        "show ip int brief",
        "show clock",
    ]


@pytest.mark.parametrize("commands", ["", "   ", [], ["", "  "]])
def test_empty_commands_are_rejected(commands) -> None:
    with pytest.raises(ValueError, match="at least one command"):
        _parse(commands=commands)


def test_commands_must_be_a_list() -> None:
    with pytest.raises(ValueError, match="list of strings"):
        _parse(commands=5)


def test_invalid_parser_is_rejected() -> None:
    with pytest.raises(ValueError, match="parser must be one of"):
        _parse(parser="regex")


def test_invalid_execution_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="execution_mode must be one of"):
        _parse(execution_mode="bulk")


def test_genie_requires_a_pyats_source() -> None:
    with pytest.raises(ValueError, match="pyats_source_id"):
        _parse(parser="genie")


def test_parser_with_config_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="parser must be 'none'"):
        _parse(parser="textfsm", execution_mode="config_mode")


def test_parser_with_auto_confirm_prompts_is_rejected() -> None:
    with pytest.raises(ValueError, match="parser must be 'none'"):
        _parse(parser="textfsm", auto_confirm_prompts="true")


def test_write_config_requires_config_mode() -> None:
    with pytest.raises(ValueError, match="requires execution_mode 'config_mode'"):
        _parse(write_config_after_execution=True)


def test_write_config_is_allowed_in_config_mode() -> None:
    parsed = _parse(execution_mode="config_mode", write_config_after_execution="yes")

    assert parsed.write_config_after_execution is True


def test_parsed_output_key_only_set_when_a_parser_is_selected() -> None:
    assert _parse(parser="none", parsed_output_key="ignored").parsed_output_key == ""
    assert _parse(parser="textfsm", parsed_output_key="out").parsed_output_key == "out"
