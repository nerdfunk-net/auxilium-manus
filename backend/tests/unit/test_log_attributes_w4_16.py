"""W4-16: log-attributes (Log Attributes) config is typed and the pretty text is split.

The pretty-text test is a characterization test: the expected lines are the output of the
87-line ``format_pretty_text`` before it was split, so the split must not change one line.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from workflow_steps.log_attributes.executor import _parse_config, format_pretty_text

_SNAPSHOT: dict[str, Any] = {
    "run_id": "run-1",
    "workflow_id": None,
    "schema_version": 3,
    "devices": {
        "d1": {
            "id": "d1",
            "name": "lab",
            "hostname": "lab.example",
            "platform": "ios",
            "network_driver": None,
            "primary_ip4": "10.0.0.1",
            "source": "list",
            "source_id": None,
            "capabilities": ["identity", "attributes"],
            "status": "ok",
            "attribute_bags": {
                "nautobot": {"role": {"name": "edge"}, "tags": []},
                "flag": {"on": True},
            },
            "parsed": {"n1": {"rows": [{"a": 1}, "x"]}},
            "command_results": {},
            "errors": [],
            "running_config_ref": {"artifact_id": "a1"},
            "startup_config_ref": None,
            "running_config_content": "hostname lab\n!\nend",
            "startup_config_content": "",
        },
        "d2": {"capabilities": None},
        "bad": "not a dict",
    },
    "pending_commands": {"d1": ["show version"]},
    "metadata": {},
}


_EXPECTED_LINES = [
    "=== Workflow Context ===",
    "Run ID: run-1",
    "Workflow ID: —",
    "Schema version: 3",
    "",
    "Devices (3):",
    "",
    "--- Device: lab (d1) ---",
    "Identity:",
    "  id: d1",
    "  name: lab",
    "  hostname: lab.example",
    "  platform: ios",
    "  network_driver: —",
    "  primary_ip4: 10.0.0.1",
    "  source: list",
    "  source_id: —",
    "  capabilities: identity, attributes",
    "  status: ok",
    "Attribute bags:",
    "  nautobot:",
    "    role:",
    "      name: edge",
    "    tags:",
    "      (empty)",
    "  flag:",
    "    on: true",
    "Parsed:",
    "  n1:",
    "    rows:",
    "      [0]:",
    "        a: 1",
    "      [1]: x",
    "Command results:",
    "  (none)",
    "Errors:",
    "  (none)",
    "Running config ref:",
    "  artifact_id: a1",
    "Running config:",
    "  hostname lab",
    "  !",
    "  end",
    "Startup config:",
    "  ",
    "",
    "--- Device: d2 (d2) ---",
    "Identity:",
    "  id: —",
    "  name: —",
    "  hostname: —",
    "  platform: —",
    "  network_driver: —",
    "  primary_ip4: —",
    "  source: —",
    "  source_id: —",
    "  capabilities: ",
    "  status: —",
    "Attribute bags:",
    "  (none)",
    "Parsed:",
    "  (none)",
    "Command results:",
    "  (none)",
    "Errors:",
    "  (none)",
    "",
    "=== Pending commands ===",
    "d1:",
    "  [0]: show version",
    "",
    "=== Workflow metadata ===",
    "(none)",
]


def test_the_pretty_text_is_unchanged_line_for_line() -> None:
    assert format_pretty_text(_SNAPSHOT).split("\n") == _EXPECTED_LINES


def test_the_parsed_config_is_a_frozen_typed_object() -> None:
    parsed = _parse_config({"output_destination": "file", "filename": " out.log ", "append": "yes"})

    assert parsed.output_destination == "file"
    assert parsed.output_format == "json"
    assert parsed.filename == "out.log"
    assert parsed.append is True
    assert parsed.show_parsed_templates is False
    assert parsed.show_device_configs is False
    with pytest.raises(dataclasses.FrozenInstanceError):
        parsed.append = False  # type: ignore[misc]
