"""Tests for the enrich-attributes executor."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from _git_helpers import acheckout_of

from core.domain_exceptions import AccessDeniedError
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.artifacts import InMemoryArtifactService
from services.workflow_context.secret_fields import SEALED_MARKER
from workflow_steps.enrich_attributes.executor import execute

_MODULE = "workflow_steps.enrich_attributes.executor"
_ROOT = "workflow_steps.common.file_source_root"


@contextmanager
def _mock_export_directory(export_dir: Path):
    service_mock = MagicMock()
    service_mock.resolved_export_directory.return_value = export_dir
    with (
        patch(f"{_ROOT}.get_db_session", return_value=MagicMock()),
        patch(f"{_ROOT}.GeneralSettingsService", return_value=service_mock),
    ):
        yield


@contextmanager
def _mock_git_repository(repo_dir: Path):
    with (
        patch(
            f"{_ROOT}.load_git_repository",
            return_value={"id": 7, "name": "lab", "url": "https://example.invalid/r.git"},
        ),
        patch(f"{_ROOT}.agit_checkout", return_value=acheckout_of(repo_dir)),
    ):
        yield


def _device(device_id: str = "device-1", *, serial: str | None = "131184641") -> DeviceContext:
    bags = {"nautobot": {"serial": serial}} if serial is not None else {}
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id,
        attribute_bags=bags,
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


def _config(**overrides) -> dict:
    base = {
        "source": "filesystem",
        "path": "data.csv",
        "delimiter": ";",
        "key_column": "serial",
        "device_attribute_path": "nautobot.serial",
        "match_mode": "match",
        "case_insensitive": False,
        "destination_path": "inventory",
        "overwrite": False,
    }
    base.update(overrides)
    return base


async def _run(config: dict, devices: dict[str, DeviceContext], csv_text: str, *, raw=None):
    run = MagicMock()
    run.id = 42
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "data.csv"
        if raw is not None:
            target.write_bytes(raw)
        else:
            target.write_text(csv_text, encoding="utf-8")
        with _mock_export_directory(Path(tmp)):
            return await execute(
                config=config,
                context=WorkflowContext(run_id="r", workflow_id="w", devices=devices),
                run=run,
                artifact_service=InMemoryArtifactService(),
                node_id="enrich-1",
                device_sessions=MagicMock(),
            )


CSV = "serial;data;site\n131184641;example data;berlin\n999;other;paris\n"


class EnrichAttributesTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_match_adds_other_columns(self) -> None:
        outcomes = await _run(_config(), {"d1": _device()}, CSV)
        self.assertEqual([o.name for o in outcomes], ["success"])
        device = outcomes[0].context.devices["d1"]
        self.assertEqual(
            device.attribute_bags["inventory"], {"data": "example data", "site": "berlin"}
        )
        self.assertNotIn("serial", device.attribute_bags["inventory"])
        self.assertIn(Capability.ATTRIBUTES, device.capabilities)

    async def test_no_match_leaves_device_unchanged_on_success(self) -> None:
        outcomes = await _run(_config(), {"d1": _device(serial="nope")}, CSV)
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertNotIn("inventory", outcomes[0].context.devices["d1"].attribute_bags)

    async def test_unresolved_device_value_is_not_matched(self) -> None:
        outcomes = await _run(_config(), {"d1": _device(serial=None)}, CSV)
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertNotIn("inventory", outcomes[0].context.devices["d1"].attribute_bags)

    async def test_case_sensitive_by_default(self) -> None:
        csv_text = "serial;data\nABC123;x\n"
        outcomes = await _run(_config(), {"d1": _device(serial="abc123")}, csv_text)
        self.assertNotIn("inventory", outcomes[0].context.devices["d1"].attribute_bags)

    async def test_case_insensitive_match(self) -> None:
        csv_text = "serial;data\nABC123;x\n"
        outcomes = await _run(
            _config(case_insensitive=True), {"d1": _device(serial="abc123")}, csv_text
        )
        self.assertEqual(
            outcomes[0].context.devices["d1"].attribute_bags["inventory"], {"data": "x"}
        )

    async def test_contains_device_value_contains_key(self) -> None:
        csv_text = "serial;data\n1184;hit\n"
        outcomes = await _run(
            _config(match_mode="contains"), {"d1": _device(serial="FOC1311841X")}, csv_text
        )
        self.assertEqual(
            outcomes[0].context.devices["d1"].attribute_bags["inventory"], {"data": "hit"}
        )

    async def test_match_mode_does_not_do_substring(self) -> None:
        csv_text = "serial;data\n1184;hit\n"
        outcomes = await _run(_config(), {"d1": _device(serial="FOC1311841X")}, csv_text)
        self.assertNotIn("inventory", outcomes[0].context.devices["d1"].attribute_bags)

    async def test_contains_ignores_empty_keys(self) -> None:
        csv_text = "serial;data\n;empty\n"
        outcomes = await _run(_config(match_mode="contains"), {"d1": _device()}, csv_text)
        self.assertNotIn("inventory", outcomes[0].context.devices["d1"].attribute_bags)

    async def test_first_matching_row_wins(self) -> None:
        csv_text = "serial;data\n131184641;first\n131184641;second\n"
        outcomes = await _run(_config(), {"d1": _device()}, csv_text)
        self.assertEqual(
            outcomes[0].context.devices["d1"].attribute_bags["inventory"], {"data": "first"}
        )

    async def test_contains_first_row_in_file_order_wins(self) -> None:
        csv_text = "serial;data\n1311;first\n131184641;second\n"
        outcomes = await _run(_config(match_mode="contains"), {"d1": _device()}, csv_text)
        self.assertEqual(
            outcomes[0].context.devices["d1"].attribute_bags["inventory"], {"data": "first"}
        )

    async def test_custom_delimiter_and_trimming(self) -> None:
        csv_text = "serial,data\n 131184641 , spaced \n"
        outcomes = await _run(_config(delimiter=","), {"d1": _device()}, csv_text)
        self.assertEqual(
            outcomes[0].context.devices["d1"].attribute_bags["inventory"], {"data": "spaced"}
        )

    async def test_tab_delimiter_word(self) -> None:
        csv_text = "serial\tdata\n131184641\tt\n"
        outcomes = await _run(_config(delimiter="tab"), {"d1": _device()}, csv_text)
        self.assertEqual(
            outcomes[0].context.devices["d1"].attribute_bags["inventory"], {"data": "t"}
        )

    async def test_utf8_bom_tolerated(self) -> None:
        raw = "﻿serial;data\n131184641;ok\n".encode()
        outcomes = await _run(_config(), {"d1": _device()}, "", raw=raw)
        self.assertEqual(
            outcomes[0].context.devices["d1"].attribute_bags["inventory"], {"data": "ok"}
        )

    async def test_overwrite_false_keeps_existing(self) -> None:
        device = _device().model_copy(
            update={
                "attribute_bags": {
                    "nautobot": {"serial": "131184641"},
                    "inventory": {"data": "old"},
                }
            }
        )
        outcomes = await _run(_config(), {"d1": device}, CSV)
        self.assertEqual(
            outcomes[0].context.devices["d1"].attribute_bags["inventory"],
            {"data": "old", "site": "berlin"},
        )

    async def test_overwrite_true_replaces(self) -> None:
        device = _device().model_copy(
            update={
                "attribute_bags": {
                    "nautobot": {"serial": "131184641"},
                    "inventory": {"data": "old"},
                }
            }
        )
        outcomes = await _run(_config(overwrite=True), {"d1": device}, CSV)
        self.assertEqual(
            outcomes[0].context.devices["d1"].attribute_bags["inventory"]["data"], "example data"
        )

    async def test_each_device_gets_its_own_row(self) -> None:
        outcomes = await _run(
            _config(),
            {"d1": _device("d1"), "d2": _device("d2", serial="999")},
            CSV,
        )
        devices = outcomes[0].context.devices
        self.assertEqual(devices["d1"].attribute_bags["inventory"]["site"], "berlin")
        self.assertEqual(devices["d2"].attribute_bags["inventory"]["site"], "paris")

    async def test_missing_key_column_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "key column"):
            await _run(_config(key_column="nope"), {"d1": _device()}, CSV)

    async def test_duplicate_header_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate"):
            await _run(_config(), {"d1": _device()}, "serial;data;data\n1;2;3\n")

    async def test_empty_file_raises(self) -> None:
        with self.assertRaises(ValueError):
            await _run(_config(), {"d1": _device()}, "")

    async def test_requires_key_column_and_device_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "key_column"):
            await _run(_config(key_column=""), {"d1": _device()}, CSV)
        with self.assertRaisesRegex(ValueError, "device_attribute_path"):
            await _run(_config(device_attribute_path=""), {"d1": _device()}, CSV)

    async def test_bad_match_mode_and_delimiter(self) -> None:
        with self.assertRaisesRegex(ValueError, "match_mode"):
            await _run(_config(match_mode="regex"), {"d1": _device()}, CSV)
        with self.assertRaisesRegex(ValueError, "delimiter"):
            await _run(_config(delimiter="ab"), {"d1": _device()}, CSV)

    async def test_reserved_destination_rejected(self) -> None:
        with self.assertRaises(ValueError):
            await _run(_config(destination_path="parsed"), {"d1": _device()}, CSV)

    async def test_path_traversal_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with _mock_export_directory(Path(tmp)):
                with self.assertRaises(AccessDeniedError):
                    await execute(
                        config=_config(path="../secret.csv"),
                        context=WorkflowContext(
                            run_id="r", workflow_id="w", devices={"d1": _device()}
                        ),
                        run=MagicMock(),
                        artifact_service=InMemoryArtifactService(),
                        node_id="n",
                        device_sessions=MagicMock(),
                    )

    async def test_missing_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with _mock_export_directory(Path(tmp)):
                with self.assertRaises(FileNotFoundError):
                    await execute(
                        config=_config(path="absent.csv"),
                        context=WorkflowContext(
                            run_id="r", workflow_id="w", devices={"d1": _device()}
                        ),
                        run=MagicMock(),
                        artifact_service=InMemoryArtifactService(),
                        node_id="n",
                        device_sessions=MagicMock(),
                    )

    async def test_git_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "data.csv").write_text(CSV, encoding="utf-8")
            with _mock_git_repository(Path(tmp)):
                outcomes = await execute(
                    config=_config(source="git", git_repository_id=7),
                    context=WorkflowContext(run_id="r", workflow_id="w", devices={"d1": _device()}),
                    run=MagicMock(),
                    artifact_service=InMemoryArtifactService(),
                    node_id="n",
                    device_sessions=MagicMock(),
                )
        self.assertEqual(
            outcomes[0].context.devices["d1"].attribute_bags["inventory"]["site"], "berlin"
        )

    async def test_git_does_not_refresh_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "data.csv").write_text(CSV, encoding="utf-8")
            with (
                patch(f"{_ROOT}.load_git_repository", return_value={"id": 7}),
                patch(f"{_ROOT}.agit_checkout", return_value=acheckout_of(Path(tmp))) as checkout,
            ):
                await execute(
                    config=_config(source="git", git_repository_id=7),
                    context=WorkflowContext(run_id="r", workflow_id="w", devices={"d1": _device()}),
                    run=MagicMock(),
                    artifact_service=InMemoryArtifactService(),
                    node_id="n",
                    device_sessions=MagicMock(),
                )
        self.assertFalse(checkout.call_args.kwargs["refresh"])

    async def test_git_refreshes_when_refresh_repository_is_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "data.csv").write_text(CSV, encoding="utf-8")
            with (
                patch(f"{_ROOT}.load_git_repository", return_value={"id": 7}),
                patch(f"{_ROOT}.agit_checkout", return_value=acheckout_of(Path(tmp))) as checkout,
            ):
                await execute(
                    config=_config(source="git", git_repository_id=7, refresh_repository=True),
                    context=WorkflowContext(run_id="r", workflow_id="w", devices={"d1": _device()}),
                    run=MagicMock(),
                    artifact_service=InMemoryArtifactService(),
                    node_id="n",
                    device_sessions=MagicMock(),
                )
        self.assertTrue(checkout.call_args.kwargs["refresh"])

    async def test_git_requires_repository_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "git_repository_id"):
            await _run(_config(source="git"), {"d1": _device()}, CSV)

    async def test_no_devices_short_circuits(self) -> None:
        outcomes = await _run(_config(), {}, CSV)
        self.assertEqual([o.name for o in outcomes], ["success"])


SEALED = {SEALED_MARKER: True, "v": 2, "ct": "ciphertext"}


def _with_bags(**extra) -> DeviceContext:
    device = _device()
    return device.model_copy(update={"attribute_bags": {**device.attribute_bags, **extra}})


class EnrichAttributesReviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_blank_destination_falls_back_to_data(self) -> None:
        for override in ({"destination_path": ""}, {"destination_path": None}):
            config = _config(**override)
            outcomes = await _run(config, {"d1": _device()}, CSV)
            self.assertEqual(
                outcomes[0].context.devices["d1"].attribute_bags["data"]["data"], "example data"
            )

    async def test_missing_destination_key_falls_back_to_data(self) -> None:
        config = _config()
        del config["destination_path"]
        outcomes = await _run(config, {"d1": _device()}, CSV)
        self.assertIn("data", outcomes[0].context.devices["d1"].attribute_bags)

    async def test_short_row_writes_no_empty_strings(self) -> None:
        csv_text = "serial;data;site\n131184641;example data\n"
        outcomes = await _run(_config(), {"d1": _device()}, csv_text)
        self.assertEqual(
            outcomes[0].context.devices["d1"].attribute_bags["inventory"], {"data": "example data"}
        )

    async def test_empty_cell_does_not_block_existing_or_later_value(self) -> None:
        csv_text = "serial;data;site\n131184641;;berlin\n"
        device = _with_bags(inventory={"data": "kept"})
        outcomes = await _run(_config(overwrite=True), {"d1": device}, csv_text)
        self.assertEqual(
            outcomes[0].context.devices["d1"].attribute_bags["inventory"],
            {"data": "kept", "site": "berlin"},
        )

    async def test_key_only_row_adds_nothing(self) -> None:
        outcomes = await _run(_config(), {"d1": _device()}, "serial;data\n131184641\n")
        self.assertNotIn(
            "data", outcomes[0].context.devices["d1"].attribute_bags.get("inventory", {})
        )

    async def test_sealed_secret_in_column_slot_is_not_overwritten(self) -> None:
        for overwrite in (False, True):
            device = _with_bags(inventory={"data": SEALED})
            outcomes = await _run(_config(overwrite=overwrite), {"d1": device}, CSV)
            self.assertEqual([o.name for o in outcomes], ["success", "failure"])
            self.assertEqual(outcomes[0].context.devices, {})
            failed = outcomes[1].context.devices["d1"]
            self.assertEqual(failed.errors[-1].code, "sealed_secret_conflict")
            self.assertEqual(failed.errors[-1].failure.kind, "bad_request")
            self.assertEqual(failed.attribute_bags["inventory"]["data"], SEALED)

    async def test_destination_that_is_a_sealed_secret_is_refused(self) -> None:
        device = _with_bags(inventory={"tacacs": SEALED})
        outcomes = await _run(_config(destination_path="inventory.tacacs"), {"d1": device}, CSV)
        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        failed = outcomes[1].context.devices["d1"]
        self.assertEqual(failed.attribute_bags["inventory"]["tacacs"], SEALED)

    async def test_sealed_device_attribute_is_not_decrypted_or_matched(self) -> None:
        device = _device().model_copy(update={"attribute_bags": {"nautobot": {"serial": SEALED}}})
        with patch("services.workflow_context.secret_fields.unwrap_secret") as unwrap:
            outcomes = await _run(
                _config(match_mode="contains"), {"d1": device}, "serial;data\n***;x\nct;y\n"
            )
        unwrap.assert_not_called()
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertNotIn("inventory", outcomes[0].context.devices["d1"].attribute_bags)

    async def test_merge_error_records_failure_info(self) -> None:
        device = _with_bags(inventory={"a": "scalar"})
        outcomes = await _run(_config(destination_path="inventory.a.b"), {"d1": device}, CSV)
        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        error = outcomes[1].context.devices["d1"].errors[-1]
        # A data condition of this device (a scalar where the path needs an object), not a bug.
        self.assertEqual(error.failure.kind, "bad_request")
        self.assertEqual(error.failure.exception_type, "ValueError")
        self.assertIn("cannot merge into", error.message)

    async def test_bad_git_flag_is_a_config_error_even_with_no_devices(self) -> None:
        for key in ("refresh_repository", "allow_stale_repository"):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    await _run(_config(**{key: "nope"}), {}, CSV)

    async def test_start_is_logged(self) -> None:
        with self.assertLogs(_MODULE, level="INFO") as logs:
            await _run(_config(), {"d1": _device()}, CSV)
        self.assertTrue(any("enrich-attributes started" in line for line in logs.output))

    async def test_file_over_size_cap_raises(self) -> None:
        with patch(f"{_MODULE}.MAX_FILE_BYTES", 10):
            with self.assertRaisesRegex(ValueError, "larger than"):
                await _run(_config(), {"d1": _device()}, CSV)

    async def test_row_cap_raises(self) -> None:
        with patch("services.csv_lookup.parse.MAX_ROWS", 1):
            with self.assertRaisesRegex(ValueError, "rows"):
                await _run(_config(), {"d1": _device()}, CSV)

    async def test_in_repo_symlink_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "real.csv").write_text(CSV, encoding="utf-8")
            (Path(tmp) / "data.csv").symlink_to(Path(tmp) / "real.csv")
            with _mock_export_directory(Path(tmp)):
                with self.assertRaises(FileNotFoundError):
                    await execute(
                        config=_config(),
                        context=WorkflowContext(
                            run_id="r", workflow_id="w", devices={"d1": _device()}
                        ),
                        run=MagicMock(),
                        artifact_service=InMemoryArtifactService(),
                        node_id="n",
                        device_sessions=MagicMock(),
                    )

    async def test_git_repository_id_must_be_a_whole_number(self) -> None:
        for bad in (True, 7.9, "abc"):
            with self.assertRaisesRegex(ValueError, "git_repository_id"):
                await _run(_config(source="git", git_repository_id=bad), {"d1": _device()}, CSV)

    async def test_git_repository_id_accepts_integral_forms(self) -> None:
        for good in (7, "7", 7.0):
            with tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / "data.csv").write_text(CSV, encoding="utf-8")
                with _mock_git_repository(Path(tmp)) as _:
                    outcomes = await execute(
                        config=_config(source="git", git_repository_id=good),
                        context=WorkflowContext(
                            run_id="r", workflow_id="w", devices={"d1": _device()}
                        ),
                        run=MagicMock(),
                        artifact_service=InMemoryArtifactService(),
                        node_id="n",
                        device_sessions=MagicMock(),
                    )
            self.assertEqual([o.name for o in outcomes], ["success"])


if __name__ == "__main__":
    unittest.main()
