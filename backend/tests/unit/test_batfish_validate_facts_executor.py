"""Tests for batfish-validate-facts executor."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import yaml

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.batfish.credentials import BatfishConnection
from workflow_steps.batfish_validate_facts.executor import execute
from workflow_steps.common.batfish_context import store_batfish_snapshot

_SERVICE_FACTORY_TARGET = "workflow_steps.batfish_validate_facts.executor.service_factory"
_LOAD_GIT_REPOSITORY_TARGET = "workflow_steps.batfish_validate_facts.executor.load_git_repository"
_CLONE_OR_PULL_TARGET = "workflow_steps.batfish_validate_facts.executor.clone_or_pull"
_COLLECT_GIT_SOURCE_FILES_TARGET = (
    "workflow_steps.batfish_validate_facts.executor.collect_git_source_files"
)


def _device(device_id: str, name: str) -> DeviceContext:
    return DeviceContext(id=device_id, name=name, hostname=name, status=DeviceStatus.OK)


def _context_with_snapshot(devices: dict[str, DeviceContext] | None = None) -> WorkflowContext:
    context = WorkflowContext(run_id="run-uuid-1", workflow_id="7", devices=devices or {})
    return store_batfish_snapshot(
        context,
        connection=BatfishConnection(host="batfish", port=9996),
        network="manus-workflow-7",
        snapshot="run-42",
    )


async def _device_with_rendered_yaml(
    artifact_service: InMemoryArtifactService,
    *,
    device_id: str,
    device_name: str,
    yaml_text: str,
    source_step_node_id: str,
    output_key: str = "rendered",
) -> DeviceContext:
    ref = await artifact_service.store(
        content=yaml_text, kind="rendered_template", device_id=device_id, run_id="1"
    )
    return DeviceContext(
        id=device_id,
        name=device_name,
        hostname=device_name,
        status=DeviceStatus.OK,
        parsed={
            output_key: {
                "artifact_ref": ref.model_dump(mode="json"),
                "step_node_id": source_step_node_id,
                "output_key": output_key,
                "size_bytes": len(yaml_text),
                "kind": "rendered_template",
            }
        },
    )


class BatfishValidateFactsFieldModeTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, *, mismatches: dict, devices: dict[str, DeviceContext], config: dict):
        run = MagicMock()
        run.id = 1
        context = _context_with_snapshot(devices)

        # The executor writes the expected-facts file into a
        # tempfile.TemporaryDirectory() that is cleaned up before execute()
        # returns, so the file must be read from *inside* the mocked call.
        captured: dict[str, str] = {}

        async def _capture_and_return(_connection, *, expected_facts_dir, **_kwargs):
            captured["written_yaml"] = (Path(expected_facts_dir) / "nodes.yaml").read_text()
            return mismatches

        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.validate_facts = AsyncMock(side_effect=_capture_and_return)
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config=config,
                context=context,
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )
        return {o.name: o for o in outcomes}, batfish, captured

    async def test_no_mismatch_routes_to_match(self) -> None:
        devices = {"device-1": _device("device-1", "R1")}
        outcomes, _, captured = await self._run(
            mismatches={},
            devices=devices,
            config={
                "facts_source": "field",
                "fact_key": "TACACS_Servers",
                "fact_value": "10.0.0.1",
            },
        )
        self.assertEqual(set(outcomes["match"].context.devices), {"device-1"})
        self.assertEqual(outcomes["mismatch"].context.devices, {})
        self.assertEqual(outcomes["failure"].context.devices, {})
        device = outcomes["match"].context.devices["device-1"]
        self.assertIn(Capability.PARSED, device.capabilities)

        # Node key must be lowercased regardless of the device's own casing,
        # and no "version" key passed through (see version gotcha).
        loaded = yaml.safe_load(captured["written_yaml"])
        self.assertIn("r1", loaded["nodes"])
        self.assertNotIn("version", loaded)

    async def test_mismatch_routes_to_mismatch_with_detail(self) -> None:
        devices = {"device-1": _device("device-1", "r1")}
        detail = {"TACACS_Servers": {"expected": ["10.0.0.1"], "actual": ["10.0.0.9"]}}
        outcomes, _, _ = await self._run(
            mismatches={"r1": detail},
            devices=devices,
            config={
                "facts_source": "field",
                "fact_key": "TACACS_Servers",
                "fact_value": "10.0.0.1",
            },
        )
        self.assertEqual(set(outcomes["mismatch"].context.devices), {"device-1"})
        self.assertEqual(outcomes["match"].context.devices, {})
        device = outcomes["mismatch"].context.devices["device-1"]
        self.assertEqual(device.parsed["node-1"]["batfish_validate_facts"]["parsed"], detail)

    async def test_list_value_field_parses_as_yaml_list(self) -> None:
        devices = {"device-1": _device("device-1", "r1")}
        _, _, captured = await self._run(
            mismatches={},
            devices=devices,
            config={
                "facts_source": "field",
                "fact_key": "TACACS_Servers",
                "fact_value": "[10.0.0.1, 10.0.0.2]",
            },
        )
        loaded = yaml.safe_load(captured["written_yaml"])
        self.assertEqual(loaded["nodes"]["r1"]["TACACS_Servers"], ["10.0.0.1", "10.0.0.2"])

    async def test_missing_fact_key_raises_value_error(self) -> None:
        run = MagicMock()
        run.id = 1
        with self.assertRaises(ValueError):
            await execute(
                config={"facts_source": "field", "fact_value": "10.0.0.1"},
                context=_context_with_snapshot(),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

    async def test_empty_devices_short_circuits(self) -> None:
        run = MagicMock()
        run.id = 1
        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.validate_facts = AsyncMock()
            service_factory_mock.get_batfish_app_service.return_value = batfish
            outcomes = await execute(
                config={"facts_source": "field", "fact_key": "Hostname", "fact_value": "r1"},
                context=_context_with_snapshot(),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )
        batfish.validate_facts.assert_not_called()
        self.assertEqual({o.name for o in outcomes}, {"match", "mismatch", "failure"})


class BatfishValidateFactsRenderedYamlModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_rendered_yaml_matched_by_lowercased_node_name(self) -> None:
        artifact_service = InMemoryArtifactService()
        device = await _device_with_rendered_yaml(
            artifact_service,
            device_id="device-1",
            device_name="R1",
            yaml_text="version: '1.0'\nnodes:\n  R1:\n    Hostname: r1\n",
            source_step_node_id="render-node",
        )
        run = MagicMock()
        run.id = 1
        context = _context_with_snapshot({"device-1": device})

        captured: dict[str, str] = {}

        async def _capture_and_return(_connection, *, expected_facts_dir, **_kwargs):
            captured["written_yaml"] = (Path(expected_facts_dir) / "nodes.yaml").read_text()
            return {}

        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.validate_facts = AsyncMock(side_effect=_capture_and_return)
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config={
                    "facts_source": "rendered_yaml",
                    "source_step_node_id": "render-node",
                    "parsed_output_key": "rendered",
                },
                context=context,
                run=run,
                artifact_service=artifact_service,
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        outcomes_by_name = {o.name: o for o in outcomes}
        self.assertEqual(set(outcomes_by_name["match"].context.devices), {"device-1"})
        loaded = yaml.safe_load(captured["written_yaml"])
        self.assertIn("r1", loaded["nodes"])
        self.assertNotIn("version", loaded)

    async def test_missing_rendered_content_routes_to_failure(self) -> None:
        device = _device("device-1", "R1")
        run = MagicMock()
        run.id = 1
        context = _context_with_snapshot({"device-1": device})

        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.validate_facts = AsyncMock()
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config={
                    "facts_source": "rendered_yaml",
                    "source_step_node_id": "render-node",
                },
                context=context,
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        batfish.validate_facts.assert_not_called()
        outcomes_by_name = {o.name: o for o in outcomes}
        self.assertEqual(set(outcomes_by_name["failure"].context.devices), {"device-1"})
        failed = outcomes_by_name["failure"].context.devices["device-1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[0].code, "missing_content")

    async def test_node_key_mismatch_routes_to_failure(self) -> None:
        artifact_service = InMemoryArtifactService()
        device = await _device_with_rendered_yaml(
            artifact_service,
            device_id="device-1",
            device_name="R1",
            yaml_text="version: '1.0'\nnodes:\n  some-other-node:\n    Hostname: x\n",
            source_step_node_id="render-node",
        )
        run = MagicMock()
        run.id = 1
        context = _context_with_snapshot({"device-1": device})

        with patch(_SERVICE_FACTORY_TARGET) as service_factory_mock:
            batfish = MagicMock()
            batfish.validate_facts = AsyncMock()
            service_factory_mock.get_batfish_app_service.return_value = batfish

            outcomes = await execute(
                config={
                    "facts_source": "rendered_yaml",
                    "source_step_node_id": "render-node",
                },
                context=context,
                run=run,
                artifact_service=artifact_service,
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        batfish.validate_facts.assert_not_called()
        outcomes_by_name = {o.name: o for o in outcomes}
        failed = outcomes_by_name["failure"].context.devices["device-1"]
        self.assertEqual(failed.errors[0].code, "node_key_mismatch")


class BatfishValidateFactsGitModeTests(unittest.IsolatedAsyncioTestCase):
    @contextmanager
    def _patch_git_helpers(self, matched_files: list[Path]):
        with (
            patch(_LOAD_GIT_REPOSITORY_TARGET, return_value={"id": 5, "name": "facts-repo"}),
            patch(_CLONE_OR_PULL_TARGET, return_value=Path("/tmp/fake-facts-repo")),
            patch(_COLLECT_GIT_SOURCE_FILES_TARGET, return_value=matched_files),
        ):
            yield

    async def test_single_file_happy_path_routes_to_match(self) -> None:
        devices = {"device-1": _device("device-1", "R1")}
        run = MagicMock()
        run.id = 1
        context = _context_with_snapshot(devices)

        with tempfile.TemporaryDirectory() as tmpdir:
            facts_file = Path(tmpdir) / "r1.yaml"
            facts_file.write_text("nodes:\n  r1:\n    Hostname: r1\n")

            with (
                patch(_SERVICE_FACTORY_TARGET) as service_factory_mock,
                self._patch_git_helpers([facts_file]),
            ):
                batfish = MagicMock()
                batfish.validate_facts = AsyncMock(return_value={})
                service_factory_mock.get_batfish_app_service.return_value = batfish

                outcomes = await execute(
                    config={
                        "facts_source": "git",
                        "git_repository_id": 5,
                        "glob_pattern": "*.yaml",
                    },
                    context=context,
                    run=run,
                    artifact_service=InMemoryArtifactService(),
                    node_id="node-1",
                    device_sessions=MagicMock(),
                )

        outcomes_by_name = {o.name: o for o in outcomes}
        self.assertEqual(set(outcomes_by_name["match"].context.devices), {"device-1"})
        batfish.validate_facts.assert_awaited_once()

    async def test_multiple_files_collision_later_file_wins(self) -> None:
        devices = {"device-1": _device("device-1", "r1")}
        run = MagicMock()
        run.id = 1
        context = _context_with_snapshot(devices)

        with tempfile.TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "01-first.yaml"
            first.write_text("nodes:\n  r1:\n    Hostname: wrong\n")
            second = Path(tmpdir) / "02-second.yaml"
            second.write_text("nodes:\n  r1:\n    Hostname: r1\n")

            captured: dict[str, str] = {}

            async def _capture_and_return(_connection, *, expected_facts_dir, **_kwargs):
                captured["written_yaml"] = (Path(expected_facts_dir) / "nodes.yaml").read_text()
                return {}

            with (
                patch(_SERVICE_FACTORY_TARGET) as service_factory_mock,
                self._patch_git_helpers([first, second]),
            ):
                batfish = MagicMock()
                batfish.validate_facts = AsyncMock(side_effect=_capture_and_return)
                service_factory_mock.get_batfish_app_service.return_value = batfish

                await execute(
                    config={
                        "facts_source": "git",
                        "git_repository_id": 5,
                        "glob_pattern": "*.yaml",
                    },
                    context=context,
                    run=run,
                    artifact_service=InMemoryArtifactService(),
                    node_id="node-1",
                    device_sessions=MagicMock(),
                )

        loaded = yaml.safe_load(captured["written_yaml"])
        self.assertEqual(loaded["nodes"]["r1"]["Hostname"], "r1")

    async def test_missing_git_repository_id_raises_value_error(self) -> None:
        run = MagicMock()
        run.id = 1
        with (
            patch(_LOAD_GIT_REPOSITORY_TARGET) as load_repo_mock,
            patch(_CLONE_OR_PULL_TARGET) as clone_mock,
            patch(_COLLECT_GIT_SOURCE_FILES_TARGET) as collect_mock,
        ):
            with self.assertRaises(ValueError):
                await execute(
                    config={"facts_source": "git", "glob_pattern": "*.yaml"},
                    context=_context_with_snapshot({"device-1": _device("device-1", "r1")}),
                    run=run,
                    artifact_service=InMemoryArtifactService(),
                    node_id="node-1",
                    device_sessions=MagicMock(),
                )
        load_repo_mock.assert_not_called()
        clone_mock.assert_not_called()
        collect_mock.assert_not_called()

    async def test_missing_glob_pattern_raises_value_error(self) -> None:
        run = MagicMock()
        run.id = 1
        with (
            patch(_LOAD_GIT_REPOSITORY_TARGET) as load_repo_mock,
            patch(_CLONE_OR_PULL_TARGET) as clone_mock,
            patch(_COLLECT_GIT_SOURCE_FILES_TARGET) as collect_mock,
        ):
            with self.assertRaises(ValueError):
                await execute(
                    config={"facts_source": "git", "git_repository_id": 5},
                    context=_context_with_snapshot({"device-1": _device("device-1", "r1")}),
                    run=run,
                    artifact_service=InMemoryArtifactService(),
                    node_id="node-1",
                    device_sessions=MagicMock(),
                )
        load_repo_mock.assert_not_called()
        clone_mock.assert_not_called()
        collect_mock.assert_not_called()

    async def test_unparseable_yaml_file_raises_value_error(self) -> None:
        devices = {"device-1": _device("device-1", "r1")}
        run = MagicMock()
        run.id = 1
        context = _context_with_snapshot(devices)

        with tempfile.TemporaryDirectory() as tmpdir:
            bad_file = Path(tmpdir) / "bad.yaml"
            # A tab in indentation is invalid YAML -- reliably raises yaml.YAMLError.
            bad_file.write_text("nodes:\n\tr1:\n\t\tHostname: r1\n")

            with (
                patch(_SERVICE_FACTORY_TARGET) as service_factory_mock,
                self._patch_git_helpers([bad_file]),
            ):
                batfish = MagicMock()
                batfish.validate_facts = AsyncMock()
                service_factory_mock.get_batfish_app_service.return_value = batfish

                with self.assertRaises(ValueError):
                    await execute(
                        config={
                            "facts_source": "git",
                            "git_repository_id": 5,
                            "glob_pattern": "*.yaml",
                        },
                        context=context,
                        run=run,
                        artifact_service=InMemoryArtifactService(),
                        node_id="node-1",
                        device_sessions=MagicMock(),
                    )
                batfish.validate_facts.assert_not_called()

    async def test_file_missing_nodes_key_raises_value_error(self) -> None:
        devices = {"device-1": _device("device-1", "r1")}
        run = MagicMock()
        run.id = 1
        context = _context_with_snapshot(devices)

        with tempfile.TemporaryDirectory() as tmpdir:
            bad_file = Path(tmpdir) / "bad.yaml"
            bad_file.write_text("hosts:\n  r1:\n    Hostname: r1\n")

            with (
                patch(_SERVICE_FACTORY_TARGET) as service_factory_mock,
                self._patch_git_helpers([bad_file]),
            ):
                batfish = MagicMock()
                batfish.validate_facts = AsyncMock()
                service_factory_mock.get_batfish_app_service.return_value = batfish

                with self.assertRaises(ValueError):
                    await execute(
                        config={
                            "facts_source": "git",
                            "git_repository_id": 5,
                            "glob_pattern": "*.yaml",
                        },
                        context=context,
                        run=run,
                        artifact_service=InMemoryArtifactService(),
                        node_id="node-1",
                        device_sessions=MagicMock(),
                    )
                batfish.validate_facts.assert_not_called()

    async def test_device_not_in_corpus_routes_to_failure(self) -> None:
        devices = {"device-1": _device("device-1", "R1")}
        run = MagicMock()
        run.id = 1
        context = _context_with_snapshot(devices)

        with tempfile.TemporaryDirectory() as tmpdir:
            facts_file = Path(tmpdir) / "other.yaml"
            facts_file.write_text("nodes:\n  some-other-node:\n    Hostname: x\n")

            with (
                patch(_SERVICE_FACTORY_TARGET) as service_factory_mock,
                self._patch_git_helpers([facts_file]),
            ):
                batfish = MagicMock()
                batfish.validate_facts = AsyncMock()
                service_factory_mock.get_batfish_app_service.return_value = batfish

                outcomes = await execute(
                    config={
                        "facts_source": "git",
                        "git_repository_id": 5,
                        "glob_pattern": "*.yaml",
                    },
                    context=context,
                    run=run,
                    artifact_service=InMemoryArtifactService(),
                    node_id="node-1",
                    device_sessions=MagicMock(),
                )

        batfish.validate_facts.assert_not_called()
        outcomes_by_name = {o.name: o for o in outcomes}
        failed = outcomes_by_name["failure"].context.devices["device-1"]
        self.assertEqual(failed.errors[0].code, "node_key_mismatch")


if __name__ == "__main__":
    unittest.main()
