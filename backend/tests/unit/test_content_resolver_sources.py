"""Coverage for the remaining content sources in
workflow_steps/common/content_resolver.py (config/command/merged/filtered/updated)."""

from __future__ import annotations

import unittest

from models.workflow_context import (
    ArtifactRef,
    CommandResult,
    DeviceContext,
    DeviceStatus,
)
from workflow_steps.common.content_resolver import (
    list_exportable_content,
    parse_content_source,
)


def _ref(artifact_id: str, kind: str, media_type: str = "text/plain") -> ArtifactRef:
    return ArtifactRef(artifact_id=artifact_id, kind=kind, media_type=media_type, size_bytes=10)


def _device(**kw) -> DeviceContext:
    base = dict(id="d1", name="lab", hostname="lab", status=DeviceStatus.OK)
    base.update(kw)
    return DeviceContext(**base)


def _parsed_entry(node_id: str, key: str, kind: str, artifact_id: str = "a1") -> dict:
    return {
        f"{node_id}.{key}": {
            "artifact_ref": _ref(artifact_id, kind, "application/json").model_dump(mode="json"),
            "kind": kind,
            "step_node_id": node_id,
        }
    }


class ParseContentSourceTests(unittest.TestCase):
    def test_valid_source_normalised(self) -> None:
        self.assertEqual(
            parse_content_source({"content_source": " Running_Config "}), "running_config"
        )

    def test_invalid_source_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_content_source({"content_source": "bogus"})


class ConfigSourceTests(unittest.TestCase):
    def test_running_config_present_and_absent(self) -> None:
        ref = _ref("cfg-1", "running_config")
        dev = _device(running_config_ref=ref)
        items = list_exportable_content(dev, content_source="running_config")
        self.assertEqual(items[0].artifact_ref.artifact_id, "cfg-1")
        self.assertEqual(
            list_exportable_content(_device(), content_source="running_config"), []
        )

    def test_startup_config_present_and_absent(self) -> None:
        dev = _device(startup_config_ref=_ref("start-1", "startup_config"))
        items = list_exportable_content(dev, content_source="startup_config")
        self.assertEqual(items[0].kind, "startup_config")
        self.assertEqual(
            list_exportable_content(_device(), content_source="startup_config"), []
        )

    def test_unknown_source_returns_empty(self) -> None:
        self.assertEqual(list_exportable_content(_device(), content_source="nonsense"), [])


class CommandOutputTests(unittest.TestCase):
    def _dev_with_commands(self) -> DeviceContext:
        return _device(
            command_results={
                "run-1": [
                    CommandResult(
                        node_id="run-1", command="show ver", success=True,
                        executed_at="2026-01-01T00:00:00Z",
                        output_ref=_ref("out-a", "command_output"),
                    ),
                    CommandResult(
                        node_id="run-1", command="show run", success=True,
                        executed_at="2026-01-02T00:00:00Z",
                        output_ref=_ref("out-b", "command_output"),
                    ),
                    CommandResult(
                        node_id="run-1", command="no output", success=False, output_ref=None
                    ),
                ]
            }
        )

    def test_command_output_requires_source_step_node_id(self) -> None:
        with self.assertRaises(ValueError):
            list_exportable_content(self._dev_with_commands(), content_source="command_output")

    def test_command_output_lists_results_with_output_ref(self) -> None:
        items = list_exportable_content(
            self._dev_with_commands(),
            content_source="command_output",
            source_step_node_id="run-1",
        )
        self.assertEqual([i.extra["command"] for i in items], ["show ver", "show run"])

    def test_command_output_unknown_node_is_empty(self) -> None:
        self.assertEqual(
            list_exportable_content(
                self._dev_with_commands(),
                content_source="command_output",
                source_step_node_id="other",
            ),
            [],
        )

    def test_latest_command_output_picks_newest(self) -> None:
        items = list_exportable_content(
            self._dev_with_commands(), content_source="latest_command_output"
        )
        self.assertEqual(items[0].artifact_ref.artifact_id, "out-b")

    def test_latest_command_output_empty_when_no_results(self) -> None:
        self.assertEqual(
            list_exportable_content(_device(), content_source="latest_command_output"), []
        )


class ParsedEntrySourceTests(unittest.TestCase):
    def test_merged_content_roundtrip(self) -> None:
        dev = _device(parsed=_parsed_entry("merge-1", "merged_content", "merged_content"))
        items = list_exportable_content(
            dev, content_source="merged_content", source_step_node_id="merge-1"
        )
        self.assertEqual(items[0].kind, "merged_content")

    def test_merged_content_requires_node_id(self) -> None:
        with self.assertRaises(ValueError):
            list_exportable_content(_device(), content_source="merged_content")

    def test_merged_content_wrong_kind_is_empty(self) -> None:
        entry = _parsed_entry("merge-1", "merged_content", "merged_content")
        entry["merge-1.merged_content"]["kind"] = "something_else"
        dev = _device(parsed=entry)
        self.assertEqual(
            list_exportable_content(
                dev, content_source="merged_content", source_step_node_id="merge-1"
            ),
            [],
        )

    def test_merged_content_missing_artifact_id_is_empty(self) -> None:
        entry = _parsed_entry("merge-1", "merged_content", "merged_content")
        entry["merge-1.merged_content"]["artifact_ref"] = {"kind": "merged_content"}
        dev = _device(parsed=entry)
        self.assertEqual(
            list_exportable_content(
                dev, content_source="merged_content", source_step_node_id="merge-1"
            ),
            [],
        )

    def test_merged_content_non_dict_entry_is_empty(self) -> None:
        dev = _device(parsed={"merge-1.merged_content": "not-a-dict"})
        self.assertEqual(
            list_exportable_content(
                dev, content_source="merged_content", source_step_node_id="merge-1"
            ),
            [],
        )

    def test_filtered_output_roundtrip_and_guards(self) -> None:
        dev = _device(parsed=_parsed_entry("f-1", "filtered_output", "filtered_output"))
        items = list_exportable_content(
            dev, content_source="filtered_output", source_step_node_id="f-1"
        )
        self.assertEqual(items[0].kind, "filtered_output")
        with self.assertRaises(ValueError):
            list_exportable_content(_device(), content_source="filtered_output")
        self.assertEqual(
            list_exportable_content(
                _device(parsed={"f-1.filtered_output": 5}),
                content_source="filtered_output",
                source_step_node_id="f-1",
            ),
            [],
        )

    def test_updated_content_roundtrip_and_guards(self) -> None:
        dev = _device(parsed=_parsed_entry("u-1", "updated_content", "updated_content"))
        items = list_exportable_content(
            dev, content_source="updated_content", source_step_node_id="u-1"
        )
        self.assertEqual(items[0].kind, "updated_content")
        with self.assertRaises(ValueError):
            list_exportable_content(_device(), content_source="updated_content")

    def test_comparison_diff_wrong_kind_is_empty(self) -> None:
        entry = _parsed_entry("c-1", "comparison_diff", "comparison_diff")
        entry["c-1.comparison_diff"]["kind"] = "nope"
        dev = _device(parsed=entry)
        self.assertEqual(
            list_exportable_content(
                dev, content_source="comparison_diff", source_step_node_id="c-1"
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
