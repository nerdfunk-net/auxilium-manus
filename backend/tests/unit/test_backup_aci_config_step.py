"""backup-aci-config: registration and executor (fake git sink and export service, no network)."""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from repositories.plugin_repository import PluginRepository
from services.aci.common.exceptions import AciAPIError, AciValidationError
from services.aci.config_export_service import AciConfigExport
from services.aci.source_config_service import AciSourceNotFoundError
from services.artifacts import InMemoryArtifactService
from services.execution.step_registry import STEP_REGISTRY
from services.plugin_registry.plugin_registry_service import PluginRegistryService
from workflow_steps.backup_aci_config.config import get_config
from workflow_steps.backup_aci_config.executor import execute

STEP_ID = "backup-aci-config"
REGISTRY_PATH = Path(__file__).resolve().parents[2] / "workflow_steps" / "registry.yaml"
EXEC = "workflow_steps.backup_aci_config.executor"

EXPORT = AciConfigExport(
    files={
        "tenants/Heroes.json": "{}\n",
        "tenants/SnV.json": "{}\n",
        "access-policies.json": "{}\n",
    },
    tenants=("Heroes", "SnV"),
)


class RegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        registry = PluginRegistryService(PluginRepository(REGISTRY_PATH)).load_registry()
        plugin = next((p for p in registry.plugins if p.id == STEP_ID), None)
        if plugin is None:
            raise AssertionError(f"{STEP_ID} is not in registry.yaml")
        cls.plugin = plugin

    def test_registry_entry(self) -> None:
        self.assertEqual(self.plugin.name, "Back Up ACI Config to Git")
        self.assertEqual(self.plugin.palette_category, "cisco")
        self.assertEqual(self.plugin.directory, "backup_aci_config")
        self.assertEqual(self.plugin.requires, [])
        self.assertEqual([o.name for o in self.plugin.outcomes], ["success", "changed"])
        self.assertTrue(self.plugin.enabled)

    def test_dispatch_and_documented_config(self) -> None:
        self.assertIs(STEP_REGISTRY[STEP_ID], execute)
        documented = {i.name: i for i in self.plugin.metadata.configuration_input}
        self.assertEqual(set(documented), set(get_config()))
        for key, value in get_config().items():
            if isinstance(value, str | bool) and key not in ("aci_source_id",):
                self.assertEqual(documented[key].default, value, msg=key)

    def test_the_layout_is_documented(self) -> None:
        text = " ".join(i.description for i in self.plugin.metadata.configuration_input)
        for word in ("tenants/", "access-policies.json", "stale_files"):
            self.assertIn(word, text)

    def test_default_config_is_a_fresh_object_each_time(self) -> None:
        first = get_config()
        first["tenants"].append("x")
        self.assertEqual(get_config()["tenants"], [])


class FakeSink:
    """Stands in for GitArtifactSink: records writes, no repository involved."""

    def __init__(self, existing=(), finalize_result=None, fail_on=None) -> None:
        self.writes: dict[str, str] = {}
        self.prepared = False
        self.finalized_with: str | None = None
        self.existing = tuple(existing)
        self.fail_on = fail_on
        self.finalize_result = finalize_result or SimpleNamespace(
            committed=True, pushed=False, commit_sha="abc123", files_changed=2, message="done"
        )
        self.has_writes = False
        self.discarded = 0
        self.repository_id = 7
        self.repository_ref = "backups"

    async def prepare(self) -> None:
        if self.fail_on == "prepare":
            raise RuntimeError("clone failed")
        self.prepared = True

    async def write_text(self, *, relative_path, content, workflow_id, run_id):
        self.writes[relative_path] = content
        self.has_writes = True
        return SimpleNamespace(path=relative_path)

    def existing_files(self, relative_dir: str) -> tuple[str, ...]:
        return self.existing

    async def discard_written(self) -> int:
        self.discarded += 1
        return len(self.writes)

    async def finalize(self, message: str):
        if self.fail_on == "finalize":
            raise RuntimeError("push rejected")
        self.finalized_with = message
        return self.finalize_result


class _Patched:
    def __init__(self, export=EXPORT, sink=None, export_error=None, lease_fails=False) -> None:
        self.sink = sink or FakeSink()
        self.service = MagicMock()
        self.service.export = AsyncMock(return_value=export, side_effect=export_error)
        self.aci_source = MagicMock()
        self.lease = MagicMock()
        self.acquire = MagicMock(
            side_effect=RuntimeError("lock busy") if lease_fails else None, return_value=self.lease
        )
        self.release = MagicMock()
        self.build_sink = MagicMock(return_value=self.sink)

    def __enter__(self):
        self._patches = [
            patch(f"{EXEC}.object_session", return_value=MagicMock()),
            patch("service_factory.build_aci_source_config_service", return_value=self.aci_source),
            patch("service_factory.build_aci_config_export_service", return_value=self.service),
            patch(f"{EXEC}.load_git_repository", return_value={"id": 7, "name": "backups"}),
            patch(f"{EXEC}._build_sink", self.build_sink),
            patch(f"{EXEC}.acquire_git_repo_lock", self.acquire),
            patch(f"{EXEC}.release_git_repo_lock", self.release),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


def _device() -> DeviceContext:
    return DeviceContext(
        id="d1",
        name="d1",
        hostname="d1",
        source="nautobot",
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


async def _run(config: dict | None = None, *, devices=()):
    run = MagicMock()
    run.id = 1
    base = {"aci_source_id": "lab", "git_repository_id": 7}
    return await execute(
        config={**base, **(config or {})},
        context=WorkflowContext(run_id="r", workflow_id="w", devices={d.id: d for d in devices}),
        run=run,
        artifact_service=InMemoryArtifactService(),
        node_id="n1",
        device_sessions=MagicMock(),
    )


class ExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_file_is_written_committed_and_reported(self) -> None:
        with _Patched() as p:
            outcomes = await _run()
        self.assertEqual(p.sink.writes, EXPORT.files)
        self.assertEqual([o.name for o in outcomes], ["success", "changed"])
        entry = outcomes[0].context.metadata["n1.aci_backup"]
        self.assertEqual(entry["files"], sorted(EXPORT.files))
        self.assertEqual(
            (entry["committed"], entry["pushed"], entry["commit_sha"], entry["files_changed"]),
            (True, False, "abc123", 2),
        )
        self.assertEqual(entry["tenants"], ["Heroes", "SnV"])
        self.assertEqual(entry["git_repository_id"], "backups")

    async def test_an_unchanged_fabric_is_a_success_without_the_changed_outcome(self) -> None:
        sink = FakeSink(
            finalize_result=SimpleNamespace(
                committed=False, pushed=False, commit_sha=None, files_changed=0, message="clean"
            )
        )
        with _Patched(sink=sink):
            outcomes = await _run()
        self.assertEqual([o.name for o in outcomes], ["success"])

    async def test_the_lock_is_held_from_prepare_to_finalize_and_always_released(self) -> None:
        with _Patched() as p:
            await _run()
        p.acquire.assert_called_once_with(7)
        p.release.assert_called_once_with(p.lease)

    async def test_a_failure_after_the_first_write_puts_the_working_tree_back(self) -> None:
        sink = FakeSink(fail_on="finalize")
        with _Patched(sink=sink):
            with self.assertRaises(RuntimeError):
                await _run()
        self.assertEqual(sink.discarded, 1)

    async def test_a_failed_write_also_puts_the_working_tree_back(self) -> None:
        sink = FakeSink()

        async def failing(**kwargs):
            sink.writes[kwargs["relative_path"]] = kwargs["content"]
            raise OSError("disk full")

        sink.write_text = failing  # type: ignore[method-assign]
        with _Patched(sink=sink):
            with self.assertRaises(OSError):
                await _run()
        self.assertEqual(sink.discarded, 1)

    async def test_a_success_and_a_failed_prepare_discard_nothing(self) -> None:
        ok = FakeSink()
        with _Patched(sink=ok):
            await _run()
        self.assertEqual(ok.discarded, 0)
        broken = FakeSink(fail_on="prepare")
        with _Patched(sink=broken):
            with self.assertRaises(RuntimeError):
                await _run()
        self.assertEqual(broken.discarded, 0)

    async def test_the_lock_is_released_when_the_commit_fails(self) -> None:
        with _Patched(sink=FakeSink(fail_on="finalize")) as p:
            with self.assertRaises(RuntimeError):
                await _run()
        p.release.assert_called_once_with(p.lease)

    async def test_a_failed_read_writes_nothing_and_fails_the_step_naming_the_objects(self) -> None:
        export = AciConfigExport(
            files={"access-policies.json": "{}\n"}, errors={"tenants/SnV.json": "too big"}
        )
        with _Patched(export=export) as p:
            with self.assertRaises(RuntimeError) as caught:
                await _run()
        self.assertIn("tenants/SnV.json", str(caught.exception))
        self.assertIn("too big", str(caught.exception))
        self.assertEqual(p.sink.writes, {})
        p.acquire.assert_not_called()  # nothing was started in the repository

    async def test_stale_tenant_files_are_reported_not_deleted(self) -> None:
        sink = FakeSink(existing=("Heroes.json", "Gone.json", "README.md"))
        with _Patched(sink=sink):
            outcomes = await _run()
        entry = outcomes[0].context.metadata["n1.aci_backup"]
        self.assertEqual(entry["stale_files"], ["tenants/Gone.json"])
        self.assertNotIn("tenants/Gone.json", sink.writes)

    async def test_a_tenant_selection_means_no_stale_report(self) -> None:
        sink = FakeSink(existing=("Gone.json",))
        with _Patched(sink=sink) as p:
            outcomes = await _run({"tenants": ["Heroes"]})
        self.assertEqual(outcomes[0].context.metadata["n1.aci_backup"]["stale_files"], [])
        p.service.export.assert_awaited_once_with(tenants=("Heroes",), include_access_policies=True)

    async def test_the_options_reach_the_sink_and_the_export(self) -> None:
        with _Patched() as p:
            await _run(
                {
                    "repository_subdirectory": "fabric1",
                    "commit": True,
                    "push": True,
                    "include_access_policies": False,
                    "commit_message": "backup of {source_id}",
                }
            )
        p.build_sink.assert_called_once_with(
            {"id": 7, "name": "backups"}, "fabric1", commit=True, push=True
        )
        p.service.export.assert_awaited_once_with(tenants=None, include_access_policies=False)
        self.assertEqual(p.sink.finalized_with, "backup of lab")

    async def test_without_commit_nothing_is_committed_and_push_is_refused(self) -> None:
        with _Patched() as p:
            await _run({"commit": False})
        p.build_sink.assert_called_once()
        with _Patched(), self.assertRaisesRegex(ValueError, "push"):
            await _run({"commit": False, "push": True})

    async def test_devices_pass_through_untouched(self) -> None:
        with _Patched():
            outcomes = await _run(devices=(_device(),))
        self.assertEqual(outcomes[0].context.devices["d1"].status, DeviceStatus.OK)

    async def test_configuration_errors_raise_before_any_io(self) -> None:
        bad = (
            {"aci_source_id": ""},
            {"git_repository_id": None},
            {"git_repository_id": 0},
            {"git_repository_id": "abc"},
            {"git_repository_id": True},
            {"tenants": "Heroes"},
            {"tenants": ["bad/name"]},
            {"tenants": [1]},
            {"repository_subdirectory": "../outside"},
            {"repository_subdirectory": "/abs"},
            {"output_key": "has space"},
            {"commit_message": "x" * 300},
        )
        for config in bad:
            with self.subTest(config=config), _Patched() as p:
                with self.assertRaises(ValueError) as caught:
                    await _run(config)
                self.assertIn(STEP_ID, str(caught.exception))
                p.service.export.assert_not_awaited()
                p.acquire.assert_not_called()

    async def test_an_unknown_aci_source_is_a_configuration_error(self) -> None:
        with _Patched() as p:
            p.aci_source.resolve_credentials.side_effect = AciSourceNotFoundError("nope")
            with self.assertRaisesRegex(ValueError, "not found"):
                await _run()

    async def test_an_unknown_tenant_is_a_configuration_error(self) -> None:
        with _Patched(export_error=AciValidationError("Tenant(s) not found on the APIC: Nope")):
            with self.assertRaisesRegex(ValueError, "Nope"):
                await _run({"tenants": ["Nope"]})

    async def test_an_apic_failure_fails_the_step_with_the_cause_kept(self) -> None:
        error = AciAPIError("apic down", code="transport")
        with _Patched(export_error=error):
            with self.assertRaises(RuntimeError) as caught:
                await _run()
        self.assertIs(caught.exception.__cause__, error)

    async def test_a_repository_that_cannot_be_prepared_fails_the_step_and_releases_the_lock(
        self,
    ) -> None:
        with _Patched(sink=FakeSink(fail_on="prepare")) as p:
            with self.assertRaises(RuntimeError):
                await _run()
        p.release.assert_called_once_with(p.lease)

    async def test_a_missing_repository_is_a_configuration_error(self) -> None:
        with _Patched():
            with patch(
                f"{EXEC}.load_git_repository", side_effect=ValueError("Git repository 7 not found")
            ):
                with self.assertRaisesRegex(ValueError, "not found"):
                    await _run()


if __name__ == "__main__":
    unittest.main()
