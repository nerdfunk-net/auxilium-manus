"""Tests for the get-age-of-backup executor (real temporary git repositories)."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from _git_helpers import acheckout_of
from git import Repo
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.models.base import Base
from core.models.device_data_records import DeviceDataRecord
from models.workflow_context import DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.device_data.device_data_service import DeviceDataService
from services.execution.run_events_reporter import RunEventContext
from services.git.commit_info import last_commit_of
from workflow_steps.get_age_of_backup.executor import execute

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
_BASE = {"git_repository_id": 7, "path_template": "{device.name}.cfg"}


def _device(device_id: str = "device-1", name: str = "lab", **overrides: object) -> DeviceContext:
    defaults: dict[str, object] = {
        "id": device_id,
        "name": name,
        "hostname": name,
        "attribute_bags": {"nautobot": {"location": {"name": "DC1"}}},
        "status": DeviceStatus.OK,
    }
    defaults.update(overrides)
    return DeviceContext(**defaults)


def _commit(repo: Repo, relative: str, text: str, when: datetime) -> str:
    path = Path(repo.working_tree_dir) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    repo.index.add([relative])
    stamp = f"{int(when.timestamp())} +0000"
    return repo.index.commit(f"backup {relative}", author_date=stamp, commit_date=stamp).hexsha


class GetAgeOfBackupExecutorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.repo = Repo.init(self.root)

        for patcher in (
            patch(
                "workflow_steps.common.file_source_root.load_git_repository",
                return_value={"id": 7, "name": "backups", "url": "https://example.invalid/r.git"},
            ),
            patch(
                "workflow_steps.common.file_source_root.agit_checkout",
                side_effect=lambda *_a, **_k: acheckout_of(self.root),
            ),
            patch("workflow_steps.get_age_of_backup.executor._utcnow", return_value=NOW),
            patch(
                "workflow_steps.get_age_of_backup.executor.current_run_event_context",
                return_value=RunEventContext(run_id=1, node_id="age-1"),
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

        emit = patch("workflow_steps.get_age_of_backup.executor.emit_run_event")
        self.emit = emit.start()
        self.addCleanup(emit.stop)

        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(engine, tables=[DeviceDataRecord.__table__])
        self.addCleanup(engine.dispose)
        self.Session = sessionmaker(bind=engine)
        patcher = patch(
            "workflow_steps.get_age_of_backup.executor.get_db_session",
            side_effect=lambda: self.Session(),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _run(self, *, config: dict, devices: dict[str, DeviceContext]):
        run = MagicMock()
        run.id = 1
        return await execute(
            config=config,
            context=WorkflowContext(run_id="run-1", workflow_id="wf-1", devices=devices),
            run=run,
            artifact_service=InMemoryArtifactService(),
            node_id="age-1",
            device_sessions=MagicMock(),
        )

    @staticmethod
    def _failed(outcomes: list, device_id: str = "device-1") -> DeviceContext:
        by_name = {o.name: o for o in outcomes}
        assert device_id not in by_name["success"].context.devices
        return by_name["failure"].context.devices[device_id]

    def _seed_marker(self, device_name: str, key: str, updated_at: datetime) -> None:
        with self.Session() as db:
            DeviceDataService(db).store_device_data(
                device_name=device_name, storage_key=key, data="ok"
            )
            db.query(DeviceDataRecord).filter_by(device_name=device_name).update(
                {"updated_at": updated_at.replace(tzinfo=None)}
            )
            db.commit()

    async def test_writes_age_in_days_into_a_separate_bag(self) -> None:
        sha = _commit(self.repo, "lab.cfg", "v1", NOW - timedelta(days=10, hours=5))

        outcomes = await self._run(config=_BASE, devices={"device-1": _device()})

        self.assertEqual([o.name for o in outcomes], ["success"])
        bag = outcomes[0].context.devices["device-1"].attribute_bags["backup_age"]
        self.assertEqual(bag["age_days"], 10)
        self.assertIsInstance(bag["age_days"], int)
        self.assertEqual(bag["commit_sha"], sha)
        self.assertEqual(bag["last_changed"], (NOW - timedelta(days=10, hours=5)).isoformat())
        self.assertNotIn("last_checked", bag)
        # the Nautobot bag is untouched
        self.assertEqual(
            outcomes[0].context.devices["device-1"].attribute_bags["nautobot"],
            {"location": {"name": "DC1"}},
        )

    async def test_uses_the_newest_commit_and_a_custom_bag_name(self) -> None:
        _commit(self.repo, "lab.cfg", "v1", NOW - timedelta(days=90))
        _commit(self.repo, "lab.cfg", "v2", NOW - timedelta(days=3))

        outcomes = await self._run(
            config={**_BASE, "output_bag": "cfg_age"}, devices={"device-1": _device()}
        )

        bag = outcomes[0].context.devices["device-1"].attribute_bags["cfg_age"]
        self.assertEqual(bag["age_days"], 3)

    async def test_path_template_with_subdirectory(self) -> None:
        _commit(self.repo, "DC1/lab.cfg", "v1", NOW - timedelta(days=2))

        outcomes = await self._run(
            config={**_BASE, "path_template": "{nautobot.location.name}/{device.name}.cfg"},
            devices={"device-1": _device()},
        )

        self.assertEqual(outcomes[0].name, "success")

    async def test_bracketed_path_reports_that_file_not_a_sibling(self) -> None:
        # "DC[1]/lab.cfg" is a git character class that also matches "DC1/lab.cfg".
        literal = _commit(self.repo, "DC[1]/lab.cfg", "old", NOW - timedelta(days=200))
        _commit(self.repo, "DC1/lab.cfg", "new", NOW - timedelta(days=1))

        outcomes = await self._run(
            config={**_BASE, "path_template": "DC[1]/{device.name}.cfg"},
            devices={"device-1": _device()},
        )

        bag = outcomes[0].context.devices["device-1"].attribute_bags["backup_age"]
        self.assertEqual(bag["commit_sha"], literal)
        self.assertEqual(bag["age_days"], 200)

    async def test_future_commit_clamps_to_zero(self) -> None:
        _commit(self.repo, "lab.cfg", "v1", NOW + timedelta(days=1))

        outcomes = await self._run(config=_BASE, devices={"device-1": _device()})

        bag = outcomes[0].context.devices["device-1"].attribute_bags["backup_age"]
        self.assertEqual(bag["age_days"], 0)

    async def test_missing_file_fails_only_that_device(self) -> None:
        _commit(self.repo, "lab.cfg", "v1", NOW - timedelta(days=1))

        outcomes = await self._run(
            config=_BASE,
            devices={"device-1": _device(), "device-2": _device("device-2", "ghost")},
        )

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(set(by_name["success"].context.devices), {"device-1"})
        failed = by_name["failure"].context.devices["device-2"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[-1].code, "backup_not_found")
        self.assertEqual(failed.errors[-1].failure.kind, "not_found")

    async def test_deleted_file_is_not_reported_as_a_backup(self) -> None:
        _commit(self.repo, "lab.cfg", "v1", NOW - timedelta(days=5))
        self.repo.index.remove(["lab.cfg"], working_tree=True)
        self.repo.index.commit("remove")

        outcomes = await self._run(config=_BASE, devices={"device-1": _device()})

        self.assertEqual(self._failed(outcomes).errors[-1].code, "backup_not_found")

    async def test_file_without_a_commit_fails(self) -> None:
        _commit(self.repo, "other.cfg", "x", NOW - timedelta(days=1))
        (self.root / "lab.cfg").write_text("untracked", encoding="utf-8")

        outcomes = await self._run(config=_BASE, devices={"device-1": _device()})

        self.assertEqual(self._failed(outcomes).errors[-1].code, "no_backup_commit")

    async def test_unresolved_placeholder_fails_the_device(self) -> None:
        outcomes = await self._run(
            config={**_BASE, "path_template": "{nautobot.site.name}/{device.name}.cfg"},
            devices={"device-1": _device()},
        )

        self.assertEqual(self._failed(outcomes).errors[-1].failure.kind, "undefined_variable")

    async def test_path_escaping_the_repository_fails(self) -> None:
        outcomes = await self._run(
            config={**_BASE, "path_template": "../{device.name}.cfg"},
            devices={"device-1": _device()},
        )

        self.assertEqual(self._failed(outcomes).errors[-1].code, "unsafe_path")

    async def test_symlink_is_refused(self) -> None:
        _commit(self.repo, "real.cfg", "v1", NOW - timedelta(days=1))
        os.symlink(self.root / "real.cfg", self.root / "lab.cfg")

        outcomes = await self._run(config=_BASE, devices={"device-1": _device()})

        self.assertEqual(self._failed(outcomes).errors[-1].code, "unsafe_path")

    async def test_marker_adds_last_checked_and_checked_age_days(self) -> None:
        _commit(self.repo, "lab.cfg", "v1", NOW - timedelta(days=40))
        self._seed_marker("lab", "backup_checked", NOW - timedelta(days=1, hours=3))

        outcomes = await self._run(
            config={**_BASE, "use_marker": True, "marker_storage_key": "backup_checked"},
            devices={"device-1": _device()},
        )

        bag = outcomes[0].context.devices["device-1"].attribute_bags["backup_age"]
        self.assertEqual(bag["age_days"], 40)
        self.assertEqual(bag["checked_age_days"], 1)
        self.assertEqual(bag["last_checked"], (NOW - timedelta(days=1, hours=3)).isoformat())

    async def test_marker_key_is_rendered_per_device(self) -> None:
        _commit(self.repo, "lab.cfg", "v1", NOW - timedelta(days=4))
        self._seed_marker("lab", "checked_DC1", NOW - timedelta(days=2))

        outcomes = await self._run(
            config={
                **_BASE,
                "use_marker": True,
                "marker_storage_key": "checked_{nautobot.location.name}",
            },
            devices={"device-1": _device()},
        )

        bag = outcomes[0].context.devices["device-1"].attribute_bags["backup_age"]
        self.assertEqual(bag["checked_age_days"], 2)

    async def test_missing_marker_gives_null_values_but_still_succeeds(self) -> None:
        _commit(self.repo, "lab.cfg", "v1", NOW - timedelta(days=4))

        outcomes = await self._run(
            config={**_BASE, "use_marker": True, "marker_storage_key": "backup_checked"},
            devices={"device-1": _device()},
        )

        self.assertEqual([o.name for o in outcomes], ["success"])
        bag = outcomes[0].context.devices["device-1"].attribute_bags["backup_age"]
        self.assertIsNone(bag["last_checked"])
        self.assertIsNone(bag["checked_age_days"])
        self.assertIs(bag["marker_found"], False)
        self.assertEqual(bag["age_days"], 4)

    async def test_found_marker_sets_marker_found_true(self) -> None:
        _commit(self.repo, "lab.cfg", "v1", NOW - timedelta(days=4))
        self._seed_marker("lab", "backup_checked", NOW - timedelta(days=1))

        outcomes = await self._run(
            config={**_BASE, "use_marker": True, "marker_storage_key": "backup_checked"},
            devices={"device-1": _device()},
        )

        bag = outcomes[0].context.devices["device-1"].attribute_bags["backup_age"]
        self.assertIs(bag["marker_found"], True)

    async def test_marker_found_is_absent_without_the_marker(self) -> None:
        _commit(self.repo, "lab.cfg", "v1", NOW - timedelta(days=4))

        outcomes = await self._run(config=_BASE, devices={"device-1": _device()})

        bag = outcomes[0].context.devices["device-1"].attribute_bags["backup_age"]
        self.assertNotIn("marker_found", bag)
        self.emit.assert_not_called()

    async def test_missing_markers_emit_one_warning_event_with_the_count(self) -> None:
        _commit(self.repo, "lab.cfg", "v1", NOW - timedelta(days=4))
        _commit(self.repo, "lab2.cfg", "v1", NOW - timedelta(days=4))
        _commit(self.repo, "lab3.cfg", "v1", NOW - timedelta(days=4))
        self._seed_marker("lab3", "backup_checked", NOW - timedelta(days=1))

        await self._run(
            config={**_BASE, "use_marker": True, "marker_storage_key": "backup_checked"},
            devices={
                "d1": _device("d1", "lab"),
                "d2": _device("d2", "lab2"),
                "d3": _device("d3", "lab3"),
            },
        )

        self.emit.assert_called_once()
        context, kwargs = self.emit.call_args.args[0], self.emit.call_args.kwargs
        self.assertEqual((context.run_id, context.node_id), (1, "age-1"))
        self.assertEqual(kwargs["kind"], "backup_marker_missing")
        self.assertEqual(kwargs["level"], "warning")
        self.assertIn("2 of 3", kwargs["message"])
        self.assertIn("backup_checked", kwargs["message"])
        self.assertIn("lab", kwargs["message"])
        self.assertNotIn("lab3", kwargs["message"])

    async def test_no_event_when_every_marker_exists(self) -> None:
        _commit(self.repo, "lab.cfg", "v1", NOW - timedelta(days=4))
        self._seed_marker("lab", "backup_checked", NOW - timedelta(days=1))

        await self._run(
            config={**_BASE, "use_marker": True, "marker_storage_key": "backup_checked"},
            devices={"device-1": _device()},
        )

        self.emit.assert_not_called()

    async def test_failed_devices_do_not_count_as_missing_markers(self) -> None:
        # No backup file for "ghost": it fails on the file, the marker is never looked up.
        await self._run(
            config={**_BASE, "use_marker": True, "marker_storage_key": "backup_checked"},
            devices={"device-2": _device("device-2", "ghost")},
        )

        self.emit.assert_not_called()

    async def test_denominator_counts_only_devices_whose_marker_was_looked_up(self) -> None:
        # 3 devices: "ghost" has no backup file (never looked up), "lab" has a file and no
        # marker, "lab2" has a file and a marker. Expected: "1 of 2", not "1 of 3".
        _commit(self.repo, "lab.cfg", "v1", NOW - timedelta(days=4))
        _commit(self.repo, "lab2.cfg", "v1", NOW - timedelta(days=4))
        self._seed_marker("lab2", "backup_checked", NOW - timedelta(days=1))

        await self._run(
            config={**_BASE, "use_marker": True, "marker_storage_key": "backup_checked"},
            devices={
                "d1": _device("d1", "lab"),
                "d2": _device("d2", "lab2"),
                "d3": _device("d3", "ghost"),
            },
        )

        message = self.emit.call_args.kwargs["message"]
        self.assertIn("1 of 2", message)
        self.assertNotIn("of 3", message)

    async def test_a_failed_marker_lookup_stays_in_the_denominator(self) -> None:
        _commit(self.repo, "lab.cfg", "v1", NOW - timedelta(days=4))
        _commit(self.repo, "lab2.cfg", "v1", NOW - timedelta(days=4))
        _commit(self.repo, "lab3.cfg", "v1", NOW - timedelta(days=4))
        self._seed_marker("lab3", "backup_checked", NOW - timedelta(days=1))
        real_get = DeviceDataService.get_device_data

        def flaky(self_: DeviceDataService, *, device_name: str, storage_key: str):
            if device_name == "lab2":
                raise RuntimeError("database went away")
            return real_get(self_, device_name=device_name, storage_key=storage_key)

        with patch.object(DeviceDataService, "get_device_data", flaky):
            outcomes = await self._run(
                config={**_BASE, "use_marker": True, "marker_storage_key": "backup_checked"},
                devices={
                    "d1": _device("d1", "lab"),
                    "d2": _device("d2", "lab2"),
                    "d3": _device("d3", "lab3"),
                },
            )

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(set(by_name["failure"].context.devices), {"d2"})
        message = self.emit.call_args.kwargs["message"]
        self.assertIn("1 of 3", message)

    async def test_an_unexpected_git_error_fails_only_that_device_and_hides_its_text(self) -> None:
        _commit(self.repo, "lab.cfg", "v1", NOW - timedelta(days=1))
        _commit(self.repo, "lab2.cfg", "v1", NOW - timedelta(days=1))
        secret = "git blew up at /srv/secret/path"
        real = last_commit_of

        def flaky(root: Path, relative: str):
            if relative == "lab2.cfg":
                raise RuntimeError(secret)
            return real(root, relative)

        with (
            patch("workflow_steps.get_age_of_backup.executor.last_commit_of", flaky),
            self.assertLogs("workflow_steps.get_age_of_backup.executor", level="ERROR") as logs,
        ):
            outcomes = await self._run(
                config=_BASE,
                devices={"d1": _device("d1", "lab"), "d2": _device("d2", "lab2")},
            )

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(set(by_name["success"].context.devices), {"d1"})
        failed = by_name["failure"].context.devices["d2"]
        self.assertEqual(failed.errors[-1].message, "RuntimeError")
        self.assertEqual(failed.errors[-1].failure.kind, "internal_error")
        self.assertNotIn(secret, str(failed.errors))
        self.assertTrue(any(r.exc_info for r in logs.records))  # the traceback stays in the log

    async def test_outcome_devices_keep_the_context_order(self) -> None:
        for name in ("a", "b", "c", "d"):
            if name != "b":
                _commit(self.repo, f"{name}.cfg", "v1", NOW - timedelta(days=1))
        devices = {n: _device(n, n) for n in ("d", "c", "b", "a")}

        outcomes = await self._run(config=_BASE, devices=devices)

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["success"].context.devices), ["d", "c", "a"])
        self.assertEqual(list(by_name["failure"].context.devices), ["b"])

    async def test_a_failed_marker_lookup_hides_its_text_and_logs_the_traceback(self) -> None:
        _commit(self.repo, "lab.cfg", "v1", NOW - timedelta(days=1))
        secret = "connection to db at 10.9.9.9 lost"

        def boom(self_: DeviceDataService, *, device_name: str, storage_key: str):
            raise RuntimeError(secret)

        with (
            patch.object(DeviceDataService, "get_device_data", boom),
            self.assertLogs("workflow_steps.get_age_of_backup.executor", level="ERROR") as logs,
        ):
            outcomes = await self._run(
                config={**_BASE, "use_marker": True, "marker_storage_key": "backup_checked"},
                devices={"d1": _device("d1", "lab")},
            )

        failed = self._failed(outcomes, "d1")
        self.assertEqual(failed.errors[-1].message, "RuntimeError")
        self.assertEqual(failed.errors[-1].failure.kind, "internal_error")
        self.assertNotIn(secret, str(failed.errors))
        self.assertTrue(any(r.exc_info for r in logs.records))

    async def test_marker_lookups_run_one_after_the_other_on_one_session(self) -> None:
        import threading
        import time

        for name in ("a", "b", "c"):
            _commit(self.repo, f"{name}.cfg", "v1", NOW - timedelta(days=1))
        lock = threading.Lock()
        state = {"now": 0, "max": 0}
        real_get = DeviceDataService.get_device_data

        def slow(self_: DeviceDataService, *, device_name: str, storage_key: str):
            with lock:
                state["now"] += 1
                state["max"] = max(state["max"], state["now"])
            time.sleep(0.05)
            try:
                return real_get(self_, device_name=device_name, storage_key=storage_key)
            finally:
                with lock:
                    state["now"] -= 1

        with patch.object(DeviceDataService, "get_device_data", slow):
            await self._run(
                config={**_BASE, "use_marker": True, "marker_storage_key": "backup_checked"},
                devices={n: _device(n, n) for n in ("a", "b", "c")},
            )

        self.assertEqual(state["max"], 1)

    async def test_failed_devices_of_both_phases_keep_the_context_order(self) -> None:
        _commit(self.repo, "x.cfg", "v1", NOW - timedelta(days=1))
        real_get = DeviceDataService.get_device_data

        def flaky(self_: DeviceDataService, *, device_name: str, storage_key: str):
            if device_name == "x":
                raise RuntimeError("down")
            return real_get(self_, device_name=device_name, storage_key=storage_key)

        with patch.object(DeviceDataService, "get_device_data", flaky):
            outcomes = await self._run(
                config={**_BASE, "use_marker": True, "marker_storage_key": "backup_checked"},
                devices={"y": _device("y", "ghost"), "x": _device("x", "x")},
            )

        failed = {o.name: o for o in outcomes}["failure"].context.devices
        self.assertEqual(list(failed), ["y", "x"])

    async def test_the_marker_session_is_closed(self) -> None:
        _commit(self.repo, "lab.cfg", "v1", NOW - timedelta(days=1))
        sessions: list[MagicMock] = []

        def make_session() -> MagicMock:
            real = self.Session()
            spy = MagicMock(wraps=real)
            sessions.append(spy)
            return spy

        with patch(
            "workflow_steps.get_age_of_backup.executor.get_db_session", side_effect=make_session
        ):
            await self._run(
                config={**_BASE, "use_marker": True, "marker_storage_key": "backup_checked"},
                devices={"d1": _device("d1", "lab")},
            )

        self.assertEqual(len(sessions), 1)
        sessions[0].close.assert_called_once()

    async def test_a_marker_key_that_renders_empty_counts_as_missing(self) -> None:
        _commit(self.repo, "lab.cfg", "v1", NOW - timedelta(days=4))
        # A row stored under the empty key must not be read as this device's marker.
        self._seed_marker("lab", "", NOW - timedelta(days=1))

        outcomes = await self._run(
            config={
                **_BASE,
                "use_marker": True,
                "marker_storage_key": "{nautobot.site.name}",  # absent attribute -> ""
            },
            devices={"device-1": _device()},
        )

        self.assertEqual([o.name for o in outcomes], ["success"])
        bag = outcomes[0].context.devices["device-1"].attribute_bags["backup_age"]
        self.assertIs(bag["marker_found"], False)
        self.assertIsNone(bag["last_checked"])
        self.assertIn("1 of 1", self.emit.call_args.kwargs["message"])

    async def test_long_lists_of_devices_are_shortened_in_the_message(self) -> None:
        devices = {}
        for index in range(8):
            name = f"sw{index}"
            _commit(self.repo, f"{name}.cfg", "v1", NOW - timedelta(days=1))
            devices[name] = _device(name, name)

        await self._run(
            config={**_BASE, "use_marker": True, "marker_storage_key": "backup_checked"},
            devices=devices,
        )

        message = self.emit.call_args.kwargs["message"]
        self.assertIn("8 of 8", message)
        self.assertIn("sw0", message)
        self.assertNotIn("sw7", message)
        self.assertIn("more", message)

    async def test_no_devices_is_a_plain_success(self) -> None:
        outcomes = await self._run(config=_BASE, devices={})

        self.assertEqual([o.name for o in outcomes], ["success"])

    async def test_config_errors_raise(self) -> None:
        bad_configs = [
            {"path_template": "{device.name}.cfg"},  # no repository
            {**_BASE, "path_template": "  "},
            {**_BASE, "output_bag": "parsed"},
            {**_BASE, "output_bag": "has space"},
            {**_BASE, "output_bag": "name"},  # a device scalar field
            {**_BASE, "use_marker": True},  # no storage key
            {**_BASE, "git_repository_id": True},  # int(True) would select repository 1
            {**_BASE, "git_repository_id": 7.9},  # int(7.9) would select repository 7
            {**_BASE, "git_repository_id": "abc"},
            {**_BASE, "git_repository_id": ""},
            {**_BASE, "git_repository_id": None},
        ]
        for config in bad_configs:
            with self.subTest(config=config), self.assertRaises(ValueError):
                await self._run(config=config, devices={"device-1": _device()})
