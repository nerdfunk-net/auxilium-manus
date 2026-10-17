"""Tests for get-ise-tacacs-key executor (mocked ISE service layer, no network)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.ise.common.exceptions import ISEAPIError, ISENotFoundError
from services.workflow_context.attribute_path import resolve_device_attribute
from workflow_steps.get_ise_tacacs_key.executor import execute


def _device(
    device_id: str,
    *,
    name: str | None = None,
    primary_ip4: str | None = None,
    attribute_bags: dict | None = None,
) -> DeviceContext:
    resolved_name = name or device_id
    return DeviceContext(
        id=device_id,
        name=resolved_name,
        hostname=resolved_name,
        primary_ip4=primary_ip4,
        attribute_bags=attribute_bags or {},
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


def _run() -> MagicMock:
    run = MagicMock()
    run.id = 1
    return run


def _context(devices: dict[str, DeviceContext]) -> WorkflowContext:
    return WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices=devices)


def _priority(*, enabled: dict[str, bool] | None = None) -> list[dict]:
    enabled = enabled or {}
    types = (
        "name_exact_32",
        "name_any",
        "location_group",
        "ip_prefix_scan",
        "ip_range_scan",
    )
    return [{"type": t, "enabled": enabled.get(t, True)} for t in types]


def _device_service() -> MagicMock:
    """A MagicMock ISENetworkDeviceService with test_connection pre-mocked to
    succeed, since execute() now does a pre-flight connectivity check."""
    device_service = MagicMock()
    device_service.test_connection = AsyncMock(return_value={"total": 0})
    return device_service


def _patches(device_service: MagicMock):
    source_config_service = MagicMock()
    source_config_service.resolve_credentials.return_value = MagicMock()
    return (
        patch(
            "workflow_steps.get_ise_tacacs_key.executor.object_session",
            return_value=MagicMock(),
        ),
        patch(
            "service_factory.build_ise_source_config_service",
            return_value=source_config_service,
        ),
        patch(
            "service_factory.build_ise_network_device_service",
            return_value=device_service,
        ),
    )


def _detail(name: str, mask: int, secret: str | None = "s3cr3t", ip: str = "10.0.0.1") -> dict:
    detail: dict = {
        "name": name,
        "NetworkDeviceIPList": [{"ipaddress": ip, "mask": mask}],
    }
    if secret is not None:
        detail["tacacsSettings"] = {"sharedSecret": secret}
    return detail


class GetIseTacacsKeyExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_ise_source_id(self) -> None:
        with self.assertRaises(ValueError):
            await execute(
                config={},
                context=_context({}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

    async def test_all_tiers_disabled_raises(self) -> None:
        device_service = _device_service()
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3, self.assertRaises(ValueError):
            await execute(
                config={
                    "ise_source_id": "lab-ise",
                    "priority": _priority(
                        enabled={
                            "name_exact_32": False,
                            "name_any": False,
                            "location_group": False,
                            "ip_prefix_scan": False,
                            "ip_range_scan": False,
                        }
                    ),
                },
                context=_context({"dev-1": _device("dev-1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

    async def test_unreachable_ise_returns_failure_outcome(self) -> None:
        device_service = _device_service()
        device_service.test_connection = AsyncMock(
            side_effect=ISEAPIError("ISE request timed out after 30 seconds")
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={"ise_source_id": "lab-ise", "priority": _priority()},
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].name, "failure")
        self.assertIn("lab-ise", outcomes[0].summary)
        # unchanged — no device processing was attempted
        self.assertIs(outcomes[0].context.devices["dev-1"].status, DeviceStatus.OK)

    async def test_login_failure_mid_run_returns_failure_outcome(self) -> None:
        device_service = _device_service()
        device_service.get_device_by_name = AsyncMock(
            side_effect=ISEAPIError("ISE ERS request failed with status 401")
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={
                    "ise_source_id": "lab-ise",
                    "priority": _priority(
                        enabled={"location_group": False, "ip_range_scan": False}
                    ),
                },
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        self.assertEqual(outcomes[0].context.devices, {})
        self.assertIn("lab-ise", outcomes[1].summary)
        self.assertEqual(outcomes[1].context.devices["dev-1"].errors[-1].code, "remote_system_lost")

    async def test_lost_connection_midway_keeps_processed_devices(self) -> None:
        device_service = _device_service()
        calls = {"n": 0}

        async def by_name(name: str) -> dict:
            calls["n"] += 1
            if calls["n"] == 3:
                raise ISEAPIError("down")
            return {
                "NetworkDevice": {
                    "id": name,
                    "name": name,
                    "NetworkDeviceIPList": [{"ipaddress": "10.0.0.1", "mask": 32}],
                    "tacacsSettings": {"sharedSecret": "k"},
                }
            }

        device_service.get_device_by_name = AsyncMock(side_effect=by_name)
        devices = {f"d{i}": _device(f"d{i}", name=f"r{i}") for i in range(1, 5)}
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={
                    "ise_source_id": "lab-ise",
                    "priority": _priority(
                        enabled={"location_group": False, "ip_range_scan": False}
                    ),
                },
                context=_context(devices),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        by = {o.name: o for o in outcomes}
        self.assertEqual(sorted(by["success"].context.devices), ["d1", "d2"])
        self.assertEqual(sorted(by["failure"].context.devices), ["d3", "d4"])

    async def test_name_not_found_is_a_tier_miss_not_a_failure(self) -> None:
        """ISENotFoundError (device genuinely not configured in ISE under
        that name) must stay a per-tier miss — only a bare ISEAPIError
        (connectivity/auth) should escalate to the failure outcome."""
        device_service = _device_service()
        device_service.get_device_by_name = AsyncMock(
            side_effect=ISENotFoundError("ISE resource not found")
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={
                    "ise_source_id": "lab-ise",
                    "priority": _priority(
                        enabled={"location_group": False, "ip_range_scan": False}
                    ),
                },
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        # DN-A: a device without a key leaves through "failure", never through "success".
        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        self.assertEqual(outcomes[0].context.devices, {})
        updated = outcomes[1].context.devices["dev-1"]
        self.assertEqual(updated.status, DeviceStatus.FAILED)
        self.assertEqual(updated.errors[-1].code, "tacacs_key_not_found")

    async def test_tier1_name_exact_32_hit(self) -> None:
        device_service = _device_service()
        device_service.get_device_by_name = AsyncMock(
            return_value={"NetworkDevice": _detail("router1", 32)}
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={"ise_source_id": "lab-ise", "priority": _priority()},
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        device_service.get_device_by_name.assert_called_once_with("router1")
        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(resolve_device_attribute(updated, "tacacs.shared_secret"), "s3cr3t")
        self.assertEqual(resolve_device_attribute(updated, "tacacs.key_strategy"), "name_exact_32")
        self.assertIn(Capability.ATTRIBUTES, updated.capabilities)
        self.assertEqual(outcomes[0].context.metadata["node-1.found_count"], 1)

        from services.workflow_context.secret_fields import is_sealed_secret

        self.assertTrue(is_sealed_secret(updated.attribute_bags["tacacs"]["shared_secret"]))

    async def test_tier1_miss_falls_through_to_tier2_single_fetch(self) -> None:
        device_service = _device_service()
        # mask=24, not /32 -> tier1 misses, tier2 (same cached fetch) accepts it.
        device_service.get_device_by_name = AsyncMock(
            return_value={"NetworkDevice": _detail("router1", 24)}
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={"ise_source_id": "lab-ise", "priority": _priority()},
                context=_context({"dev-1": _device("dev-1", name="router1")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        # cached: get_device_by_name called once even though 2 tiers use it
        device_service.get_device_by_name.assert_called_once_with("router1")
        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(resolve_device_attribute(updated, "tacacs.shared_secret"), "s3cr3t")
        self.assertEqual(resolve_device_attribute(updated, "tacacs.key_strategy"), "name_any")

    async def test_location_group_tier_skipped_without_nautobot_location(self) -> None:
        device_service = _device_service()
        device_service.get_device_by_name = AsyncMock(side_effect=Exception("should not be called"))
        device_service.list_devices_by_group = AsyncMock()
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={
                    "ise_source_id": "lab-ise",
                    "priority": _priority(
                        enabled={
                            "name_exact_32": False,
                            "name_any": False,
                            "ip_prefix_scan": False,
                            "ip_range_scan": False,
                        }
                    ),
                },
                context=_context({"dev-1": _device("dev-1", name="lab")}),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        device_service.list_devices_by_group.assert_not_called()
        updated = outcomes[1].context.devices["dev-1"]
        self.assertEqual(updated.status, DeviceStatus.FAILED)
        self.assertEqual(outcomes[0].context.metadata["node-1.not_found_count"], 1)

    async def test_location_group_tier_hit(self) -> None:
        device_service = _device_service()
        device_service.list_devices_by_group = AsyncMock(
            return_value={
                "SearchResult": {
                    "total": 1,
                    "resources": [{"id": "grp-1"}],
                    "nextPage": None,
                }
            }
        )
        device_service.get_device = AsyncMock(
            return_value={"NetworkDevice": _detail("site-group", 24)}
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={
                    "ise_source_id": "lab-ise",
                    "priority": _priority(
                        enabled={
                            "name_exact_32": False,
                            "name_any": False,
                            "ip_prefix_scan": False,
                            "ip_range_scan": False,
                        }
                    ),
                    "location_group_prefix": "All Locations",
                },
                context=_context(
                    {
                        "dev-1": _device(
                            "dev-1",
                            name="lab",
                            attribute_bags={"nautobot": {"location": {"name": "Building1"}}},
                        )
                    }
                ),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        (call_args,), _ = device_service.list_devices_by_group.call_args
        self.assertEqual(call_args, "Location#All Locations#Building1")
        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(resolve_device_attribute(updated, "tacacs.shared_secret"), "s3cr3t")
        self.assertEqual(resolve_device_attribute(updated, "tacacs.key_strategy"), "location_group")

    async def test_ip_prefix_scan_matches_wide_prefix(self) -> None:
        device_service = _device_service()

        async def list_devices_side_effect(*, filter_: str | None = None, **_kwargs):
            if filter_ == "ipaddress.EQ.192.168.178.0":
                return {
                    "SearchResult": {
                        "total": 1,
                        "resources": [{"id": "grp-1"}],
                        "nextPage": None,
                    }
                }
            return {"SearchResult": {"total": 0, "resources": [], "nextPage": None}}

        device_service.list_devices = AsyncMock(side_effect=list_devices_side_effect)
        device_service.get_device = AsyncMock(
            return_value={"NetworkDevice": _detail("lab-subnet", 24, ip="192.168.178.0")}
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={
                    "ise_source_id": "lab-ise",
                    "priority": _priority(
                        enabled={
                            "name_exact_32": False,
                            "name_any": False,
                            "location_group": False,
                        }
                    ),
                },
                context=_context(
                    {"dev-1": _device("dev-1", name="lab", primary_ip4="192.168.178.240/24")}
                ),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(resolve_device_attribute(updated, "tacacs.shared_secret"), "s3cr3t")
        self.assertEqual(resolve_device_attribute(updated, "tacacs.key_strategy"), "ip_prefix_scan")

    async def test_prefix_scan_ignores_entry_that_does_not_contain_the_device(self) -> None:
        device_service = _device_service()

        async def list_devices_side_effect(*, filter_: str | None = None, **_kwargs):
            if filter_ == "ipaddress.EQ.10.0.0.0":
                return {"SearchResult": {"total": 1, "resources": [{"id": "x"}], "nextPage": None}}
            return {"SearchResult": {"total": 0, "resources": [], "nextPage": None}}

        device_service.list_devices = AsyncMock(side_effect=list_devices_side_effect)
        # the entry ISE returns covers 10.0.0.0/30 only; the device is 10.0.0.5
        device_service.get_device = AsyncMock(
            return_value={"NetworkDevice": _detail("other", 30, ip="10.0.0.0")}
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={
                    "ise_source_id": "lab-ise",
                    "priority": _priority(
                        enabled={
                            "name_exact_32": False,
                            "name_any": False,
                            "location_group": False,
                            "ip_range_scan": False,
                        }
                    ),
                },
                context=_context(
                    {"dev-1": _device("dev-1", name="lab", primary_ip4="10.0.0.5/24")}
                ),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )
        by_name = {o.name: o for o in outcomes}
        self.assertNotIn("dev-1", by_name["success"].context.devices)
        self.assertEqual(
            by_name["failure"].context.devices["dev-1"].errors[-1].code, "tacacs_key_not_found"
        )

    async def test_range_scan_fetches_inventory_once_for_many_devices(self) -> None:
        device_service = _device_service()
        device_service.list_devices = AsyncMock(
            return_value={
                "SearchResult": {
                    "total": 3,
                    "resources": [{"id": "e1"}, {"id": "e2"}, {"id": "e3"}],
                    "nextPage": None,
                }
            }
        )
        device_service.get_device = AsyncMock(
            return_value={"NetworkDevice": _detail("range", 24, ip="10.9.0.0")}
        )
        devices = {
            f"d{i}": _device(f"d{i}", name=f"r{i}", primary_ip4=f"10.9.0.{i + 1}/24")
            for i in range(10)
        }
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={
                    "ise_source_id": "lab-ise",
                    "priority": _priority(
                        enabled={
                            "name_exact_32": False,
                            "name_any": False,
                            "location_group": False,
                            "ip_prefix_scan": False,
                        }
                    ),
                },
                context=_context(devices),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )
        self.assertEqual(len(outcomes[0].context.devices), 10)
        # the inventory (3 detail records) is fetched once, not once per device
        self.assertEqual(device_service.get_device.await_count, 3)

    async def test_ip_prefix_scan_falls_back_to_nautobot_attribute_bag(self) -> None:
        """Regression test: a device from Get from List has no top-level
        primary_ip4 — it only appears in attribute_bags["nautobot"]["primary_ip4"]
        after a Get Nautobot Attributes step. ip_prefix_scan must still find it."""
        device_service = _device_service()

        async def list_devices_side_effect(*, filter_: str | None = None, **_kwargs):
            if filter_ == "ipaddress.EQ.192.168.178.0":
                return {
                    "SearchResult": {
                        "total": 1,
                        "resources": [{"id": "grp-1"}],
                        "nextPage": None,
                    }
                }
            return {"SearchResult": {"total": 0, "resources": [], "nextPage": None}}

        device_service.list_devices = AsyncMock(side_effect=list_devices_side_effect)
        device_service.get_device = AsyncMock(
            return_value={"NetworkDevice": _detail("lab-subnet", 24, ip="192.168.178.0")}
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={
                    "ise_source_id": "lab-ise",
                    "priority": _priority(
                        enabled={
                            "name_exact_32": False,
                            "name_any": False,
                            "location_group": False,
                        }
                    ),
                },
                context=_context(
                    {
                        "dev-1": _device(
                            "dev-1",
                            name="lab",
                            primary_ip4=None,
                            attribute_bags={
                                "nautobot": {"primary_ip4": {"address": "192.168.178.240/24"}}
                            },
                        )
                    }
                ),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(resolve_device_attribute(updated, "tacacs.shared_secret"), "s3cr3t")

    async def test_ip_prefix_scan_exhausts_with_no_match(self) -> None:
        device_service = _device_service()
        device_service.list_devices = AsyncMock(
            return_value={"SearchResult": {"total": 0, "resources": [], "nextPage": None}}
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={
                    "ise_source_id": "lab-ise",
                    "priority": _priority(
                        enabled={
                            "name_exact_32": False,
                            "name_any": False,
                            "location_group": False,
                            "ip_range_scan": False,
                        }
                    ),
                },
                context=_context(
                    {"dev-1": _device("dev-1", name="lab", primary_ip4="192.168.178.240/24")}
                ),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        # 32 down to 8 inclusive = 25 calls
        self.assertEqual(device_service.list_devices.await_count, 25)
        updated = outcomes[1].context.devices["dev-1"]
        self.assertEqual(updated.status, DeviceStatus.FAILED)
        self.assertEqual(updated.errors[-1].code, "tacacs_key_not_found")
        self.assertEqual(outcomes[0].context.metadata["node-1.not_found_count"], 1)

    async def test_ip_prefix_scan_alone_misses_range_entry(self) -> None:
        """ip_prefix_scan's exact-match EQ filter can never find an ISE entry
        stored as a literal range string (e.g. "192.168.178.1-254") — there is
        no clean CIDR network address to query. This is why ip_range_scan
        exists as its own, lower-priority tier."""
        device_service = _device_service()
        device_service.list_devices = AsyncMock(
            return_value={"SearchResult": {"total": 0, "resources": [], "nextPage": None}}
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={
                    "ise_source_id": "lab-ise",
                    "priority": _priority(
                        enabled={
                            "name_exact_32": False,
                            "name_any": False,
                            "location_group": False,
                            "ip_range_scan": False,
                        }
                    ),
                },
                context=_context(
                    {"dev-1": _device("dev-1", name="lab", primary_ip4="192.168.178.240/24")}
                ),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        updated = outcomes[1].context.devices["dev-1"]
        self.assertEqual(updated.status, DeviceStatus.FAILED)

    async def test_ip_range_scan_matches_hyphen_range(self) -> None:
        device_service = _device_service()
        device_service.list_devices = AsyncMock(
            return_value={
                "SearchResult": {"total": 1, "resources": [{"id": "grp-1"}], "nextPage": None}
            }
        )
        device_service.get_device = AsyncMock(
            return_value={
                "NetworkDevice": {
                    "name": "xxx",
                    "NetworkDeviceIPList": [{"ipaddress": "192.168.178.1-254", "mask": 32}],
                    "tacacsSettings": {"sharedSecret": "s3cr3t"},
                }
            }
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={
                    "ise_source_id": "lab-ise",
                    "priority": _priority(
                        enabled={
                            "name_exact_32": False,
                            "name_any": False,
                            "location_group": False,
                            "ip_prefix_scan": False,
                        }
                    ),
                },
                context=_context(
                    {"dev-1": _device("dev-1", name="lab", primary_ip4="192.168.178.240/24")}
                ),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(resolve_device_attribute(updated, "tacacs.shared_secret"), "s3cr3t")
        self.assertEqual(resolve_device_attribute(updated, "tacacs.key_strategy"), "ip_range_scan")

    async def test_ip_range_scan_matches_wildcard(self) -> None:
        device_service = _device_service()
        device_service.list_devices = AsyncMock(
            return_value={
                "SearchResult": {"total": 1, "resources": [{"id": "grp-1"}], "nextPage": None}
            }
        )
        device_service.get_device = AsyncMock(
            return_value={
                "NetworkDevice": {
                    "name": "xxx",
                    "NetworkDeviceIPList": [{"ipaddress": "192.168.178.*", "mask": 32}],
                    "tacacsSettings": {"sharedSecret": "s3cr3t"},
                }
            }
        )
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={
                    "ise_source_id": "lab-ise",
                    "priority": _priority(
                        enabled={
                            "name_exact_32": False,
                            "name_any": False,
                            "location_group": False,
                            "ip_prefix_scan": False,
                        }
                    ),
                },
                context=_context(
                    {"dev-1": _device("dev-1", name="lab", primary_ip4="192.168.178.240/24")}
                ),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(resolve_device_attribute(updated, "tacacs.shared_secret"), "s3cr3t")

    async def test_device_with_existing_key_is_skipped(self) -> None:
        device_service = _device_service()
        device_service.get_device_by_name = AsyncMock(side_effect=Exception("should not be called"))
        p1, p2, p3 = _patches(device_service)
        with p1, p2, p3:
            outcomes = await execute(
                config={"ise_source_id": "lab-ise", "priority": _priority()},
                context=_context(
                    {
                        "dev-1": _device(
                            "dev-1",
                            name="router1",
                            attribute_bags={"tacacs": {"shared_secret": "already-known"}},
                        )
                    }
                ),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="node-1",
                device_sessions=MagicMock(),
            )

        device_service.get_device_by_name.assert_not_called()
        updated = outcomes[0].context.devices["dev-1"]
        self.assertEqual(resolve_device_attribute(updated, "tacacs.shared_secret"), "already-known")
        self.assertEqual(outcomes[0].context.metadata["node-1.already_present_count"], 1)
        self.assertEqual(outcomes[0].context.metadata["node-1.found_count"], 0)


if __name__ == "__main__":
    unittest.main()
