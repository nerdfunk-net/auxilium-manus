"""Tests for the get-from-config workflow step executor."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from models.workflow_context import Capability, WorkflowContext
from services.git.content_search_service import GitContentMatch
from workflow_steps.get_from_config.executor import execute as get_from_config

_MODULE = "workflow_steps.get_from_config.executor"


class GetFromConfigExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.run = MagicMock()
        self.run.id = 7
        self.artifact_service = MagicMock()
        self.context = WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1")
        self.repository = {
            "id": 7,
            "name": "prod-lab",
            "url": "https://example.com/repo.git",
        }

    def _patch_common(self, *, matches: list[GitContentMatch]):
        search_service = MagicMock()
        search_service.search.return_value = (matches, len(matches))
        search_service_cls = MagicMock(return_value=search_service)

        return (
            patch(f"{_MODULE}.load_git_repository", return_value=self.repository),
            patch(f"{_MODULE}.clone_or_pull", return_value=Path("/tmp/prod-lab")),
            patch(f"{_MODULE}.GitContentSearchService", search_service_cls),
        )

    async def test_adds_device_for_matching_file(self) -> None:
        matches = [
            GitContentMatch(
                file_path="configs/router1.cfg",
                content="Current configuration : 100 bytes\nhostname router1\n! FINDME\n",
                line_number=2,
                line_content="! FINDME",
                commit=None,
                commit_message=None,
                commit_date=None,
            )
        ]

        patches = self._patch_common(matches=matches)
        with patches[0], patches[1], patches[2]:
            outcomes = await get_from_config(
                config={"git_repository_id": 7, "search_text": "FINDME"},
                context=self.context,
                run=self.run,
                artifact_service=self.artifact_service,
                node_id="get-from-config-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(len(outcomes), 1)
        outcome = outcomes[0]
        self.assertEqual(outcome.name, "success")
        devices = list(outcome.context.devices.values())
        self.assertEqual(len(devices), 1)
        device = devices[0]
        self.assertEqual(device.name, "router1")
        self.assertEqual(device.hostname, "router1")
        self.assertIn(Capability.IDENTITY, device.capabilities)
        self.assertEqual(device.attribute_bags["git"]["file_path"], "configs/router1.cfg")

    async def test_dedups_matches_with_same_hostname(self) -> None:
        matches = [
            GitContentMatch(
                file_path="configs/a.cfg",
                content="Current configuration : 100 bytes\nhostname dupe-router\n! FINDME\n",
                line_number=2,
                line_content="! FINDME",
                commit=None,
                commit_message=None,
                commit_date=None,
            ),
            GitContentMatch(
                file_path="configs/b.cfg",
                content="Current configuration : 100 bytes\nhostname DUPE-ROUTER\n! FINDME\n",
                line_number=2,
                line_content="! FINDME",
                commit=None,
                commit_message=None,
                commit_date=None,
            ),
        ]

        patches = self._patch_common(matches=matches)
        with patches[0], patches[1], patches[2]:
            outcomes = await get_from_config(
                config={"git_repository_id": 7, "search_text": "FINDME"},
                context=self.context,
                run=self.run,
                artifact_service=self.artifact_service,
                node_id="get-from-config-1",
                device_sessions=MagicMock(),
            )

        devices = list(outcomes[0].context.devices.values())
        self.assertEqual(len(devices), 1)

    async def test_skips_file_with_no_hostname(self) -> None:
        matches = [
            GitContentMatch(
                file_path="configs/no-hostname.cfg",
                content=(
                    "Current configuration : 100 bytes\n"
                    "! FINDME but no hostname line\ninterface Gi0/1\n"
                ),
                line_number=1,
                line_content="! FINDME but no hostname line",
                commit=None,
                commit_message=None,
                commit_date=None,
            )
        ]

        patches = self._patch_common(matches=matches)
        with patches[0], patches[1], patches[2]:
            outcomes = await get_from_config(
                config={"git_repository_id": 7, "search_text": "FINDME"},
                context=self.context,
                run=self.run,
                artifact_service=self.artifact_service,
                node_id="get-from-config-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(outcomes[0].context.devices, {})

    async def test_zero_matches_is_trivial_success(self) -> None:
        patches = self._patch_common(matches=[])
        with patches[0], patches[1], patches[2]:
            outcomes = await get_from_config(
                config={"git_repository_id": 7, "search_text": "NOTHING"},
                context=self.context,
                run=self.run,
                artifact_service=self.artifact_service,
                node_id="get-from-config-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "success")
        self.assertEqual(outcomes[0].context.devices, {})

    async def test_fan_out_metadata_stamped_when_enabled(self) -> None:
        matches = [
            GitContentMatch(
                file_path="configs/router2.cfg",
                content="Current configuration : 100 bytes\nhostname router2\n! FINDME\n",
                line_number=2,
                line_content="! FINDME",
                commit=None,
                commit_message=None,
                commit_date=None,
            )
        ]

        patches = self._patch_common(matches=matches)
        with patches[0], patches[1], patches[2]:
            outcomes = await get_from_config(
                config={
                    "git_repository_id": 7,
                    "search_text": "FINDME",
                    "fan_out": {"enabled": True, "mode": "per_device"},
                },
                context=self.context,
                run=self.run,
                artifact_service=self.artifact_service,
                node_id="get-from-config-1",
                device_sessions=MagicMock(),
            )

        fan_out = outcomes[0].context.metadata["_fan_out"]
        self.assertTrue(fan_out["enabled"])
        self.assertEqual(fan_out["mode"], "per_device")

    async def test_missing_git_repository_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            await get_from_config(
                config={"search_text": "FINDME"},
                context=self.context,
                run=self.run,
                artifact_service=self.artifact_service,
                node_id="get-from-config-1",
                device_sessions=MagicMock(),
            )

    async def test_missing_search_text_raises(self) -> None:
        with self.assertRaises(ValueError):
            await get_from_config(
                config={"git_repository_id": 7},
                context=self.context,
                run=self.run,
                artifact_service=self.artifact_service,
                node_id="get-from-config-1",
                device_sessions=MagicMock(),
            )

    async def test_repository_lookup_error_surfaces_as_value_error(self) -> None:
        with (
            patch(
                f"{_MODULE}.load_git_repository",
                side_effect=ValueError("Git repository 7 not found"),
            ),
            self.assertRaises(ValueError),
        ):
            await get_from_config(
                config={"git_repository_id": 7, "search_text": "FINDME"},
                context=self.context,
                run=self.run,
                artifact_service=self.artifact_service,
                node_id="get-from-config-1",
                device_sessions=MagicMock(),
            )


if __name__ == "__main__":
    unittest.main()
