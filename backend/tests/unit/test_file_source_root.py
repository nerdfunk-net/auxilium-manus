"""Tests for the shared file-source root resolver."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import AsyncExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

from _git_helpers import acheckout_of

from workflow_steps.common.file_source_root import resolve_source_root

_MODULE = "workflow_steps.common.file_source_root"


class ResolveSourceRootTests(unittest.IsolatedAsyncioTestCase):
    async def test_filesystem_uses_export_directory(self) -> None:
        service = MagicMock()
        service.resolved_export_directory.return_value = Path("/exports")
        with (
            patch(f"{_MODULE}.get_db_session", return_value=MagicMock()),
            patch(f"{_MODULE}.GeneralSettingsService", return_value=service),
        ):
            async with AsyncExitStack() as stack:
                root = await resolve_source_root(
                    source="filesystem", git_repository_id=None, stack=stack, step_id="s"
                )
        self.assertEqual(root, Path("/exports"))

    async def test_git_requires_repository_id(self) -> None:
        async with AsyncExitStack() as stack:
            with self.assertRaisesRegex(ValueError, "s: git_repository_id is required"):
                await resolve_source_root(
                    source="git", git_repository_id=None, stack=stack, step_id="s"
                )

    async def test_git_passes_allow_stale_to_checkout(self) -> None:
        for allow_stale in (False, True):
            with tempfile.TemporaryDirectory() as tmp:
                with (
                    patch(f"{_MODULE}.load_git_repository", return_value={"id": 7}),
                    patch(
                        f"{_MODULE}.agit_checkout", return_value=acheckout_of(Path(tmp))
                    ) as checkout,
                ):
                    async with AsyncExitStack() as stack:
                        root = await resolve_source_root(
                            source="git",
                            git_repository_id=7,
                            stack=stack,
                            allow_stale=allow_stale,
                            step_id="s",
                        )
                self.assertEqual(root, Path(tmp))
                checkout.assert_called_once_with({"id": 7}, allow_stale=allow_stale, refresh=True)

    async def test_git_passes_refresh_false_to_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch(f"{_MODULE}.load_git_repository", return_value={"id": 7}),
                patch(f"{_MODULE}.agit_checkout", return_value=acheckout_of(Path(tmp))) as checkout,
            ):
                async with AsyncExitStack() as stack:
                    await resolve_source_root(
                        source="git",
                        git_repository_id=7,
                        stack=stack,
                        refresh=False,
                        step_id="s",
                    )
            checkout.assert_called_once_with({"id": 7}, allow_stale=False, refresh=False)

    async def test_git_lease_is_released_when_the_stack_closes(self) -> None:
        events: list[str] = []

        class _Lease:
            async def __aenter__(self) -> Path:
                events.append("enter")
                return Path("/repo")

            async def __aexit__(self, *exc: object) -> None:
                events.append("exit")

        with (
            patch(f"{_MODULE}.load_git_repository", return_value={"id": 7}),
            patch(f"{_MODULE}.agit_checkout", return_value=_Lease()),
        ):
            async with AsyncExitStack() as stack:
                await resolve_source_root(
                    source="git", git_repository_id=7, stack=stack, step_id="s"
                )
                self.assertEqual(events, ["enter"])
        self.assertEqual(events, ["enter", "exit"])


if __name__ == "__main__":
    unittest.main()
