"""Tests for route-on-attribute executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from core.crypto import EncryptionService
from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.route_on_attribute.executor import execute

_ENC = EncryptionService("test-secret-key-for-route-on-attribute")


def _device(
    device_id: str,
    *,
    network_driver: str | None = None,
    attribute_bags: dict | None = None,
    parsed: dict | None = None,
) -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id,
        network_driver=network_driver,
        attribute_bags=attribute_bags or {},
        parsed=parsed or {},
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


class RouteOnAttributeExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_splits_devices_by_network_driver(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "ios-1": _device("ios-1", network_driver="cisco_ios"),
                "nxos-1": _device("nxos-1", network_driver="cisco_nxos"),
            },
        )

        outcomes = await execute(
            config={
                "attribute_path": "device.network_driver",
                "routes": [
                    {"outcome": "ios", "values": ["cisco_ios", "ios"]},
                    {"outcome": "nxos", "values": ["cisco_nxos", "nxos"]},
                ],
                "default_outcome": "unmatched",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="route-1",
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(set(by_name), {"ios", "nxos", "unmatched"})
        self.assertEqual(list(by_name["ios"].context.devices), ["ios-1"])
        self.assertEqual(list(by_name["nxos"].context.devices), ["nxos-1"])
        self.assertEqual(by_name["unmatched"].context.devices, {})

    async def test_routes_by_nautobot_attribute(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "sw-1": _device(
                    "sw-1",
                    attribute_bags={"nautobot": {"role": {"name": "access-switch"}}},
                ),
                "rt-1": _device(
                    "rt-1",
                    attribute_bags={"nautobot": {"role": {"name": "core-router"}}},
                ),
            },
        )

        outcomes = await execute(
            config={
                "attribute_path": "nautobot.role.name",
                "routes": [
                    {"outcome": "access", "values": ["access-switch"]},
                    {"outcome": "core", "values": ["core-router"]},
                ],
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="route-2",
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["access"].context.devices), ["sw-1"])
        self.assertEqual(list(by_name["core"].context.devices), ["rt-1"])

    async def test_default_outcome_catches_unmatched_devices(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "junos-1": _device("junos-1", network_driver="junos"),
            },
        )

        outcomes = await execute(
            config={
                "attribute_path": "network_driver",
                "routes": [{"outcome": "ios", "values": ["cisco_ios"]}],
                "default_outcome": "other",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="route-3",
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(by_name["ios"].context.devices, {})
        self.assertEqual(list(by_name["other"].context.devices), ["junos-1"])

    async def test_fails_when_unmatched_without_default(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "junos-1": _device("junos-1", network_driver="junos"),
            },
        )

        with self.assertRaises(ValueError):
            await execute(
                config={
                    "attribute_path": "network_driver",
                    "routes": [{"outcome": "ios", "values": ["cisco_ios"]}],
                },
                context=context,
                run=run,
                artifact_service=MagicMock(),
                node_id="route-4",
            )

    async def test_routes_on_absent_vs_present_tacacs_key(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "has-key": _device(
                    "has-key", attribute_bags={"tacacs": {"shared_secret": "s3cr3t"}}
                ),
                "no-key": _device("no-key"),
            },
        )

        outcomes = await execute(
            config={
                "attribute_path": "tacacs.shared_secret",
                "routes": [
                    {"outcome": "has-key", "values": ["{exists}"]},
                    {"outcome": "no-key", "values": ["{absent}", "{null}", "{empty}"]},
                ],
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="route-6",
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["has-key"].context.devices), ["has-key"])
        self.assertEqual(list(by_name["no-key"].context.devices), ["no-key"])

    async def test_routes_on_sealed_secret_without_decrypting(self) -> None:
        """A sealed TACACS+ key must still classify as {exists} — route-on-attribute
        must never need to decrypt the secret just to check presence."""
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "has-key": _device(
                    "has-key",
                    attribute_bags={
                        "tacacs": {"shared_secret": seal_secret("s3cr3t", encryption=_ENC)}
                    },
                ),
                "no-key": _device("no-key"),
            },
        )

        outcomes = await execute(
            config={
                "attribute_path": "tacacs.shared_secret",
                "routes": [
                    {"outcome": "has-key", "values": ["{exists}"]},
                    {"outcome": "no-key", "values": ["{absent}", "{null}", "{empty}"]},
                ],
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="route-6b",
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["has-key"].context.devices), ["has-key"])
        self.assertEqual(list(by_name["no-key"].context.devices), ["no-key"])

    async def test_null_special_value_matches_explicit_none(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "null-1": _device(
                    "null-1", attribute_bags={"tacacs": {"shared_secret": None}}
                ),
            },
        )

        outcomes = await execute(
            config={
                "attribute_path": "tacacs.shared_secret",
                "routes": [
                    {"outcome": "null-route", "values": ["{null}"]},
                    {"outcome": "absent-route", "values": ["{absent}"]},
                ],
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="route-7",
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["null-route"].context.devices), ["null-1"])
        self.assertEqual(by_name["absent-route"].context.devices, {})

    async def test_empty_special_value_matches_blank_string(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "empty-1": _device(
                    "empty-1", attribute_bags={"tacacs": {"shared_secret": "   "}}
                ),
            },
        )

        outcomes = await execute(
            config={
                "attribute_path": "tacacs.shared_secret",
                "routes": [
                    {"outcome": "empty-route", "values": ["{empty}"]},
                    {"outcome": "exists-route", "values": ["{exists}"]},
                ],
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="route-8",
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["empty-route"].context.devices), ["empty-1"])
        self.assertEqual(by_name["exists-route"].context.devices, {})

    async def test_special_values_combine_with_literal_values(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "ios-1": _device("ios-1", network_driver="cisco_ios"),
                "missing-1": _device("missing-1"),
            },
        )

        outcomes = await execute(
            config={
                "attribute_path": "device.network_driver",
                "routes": [
                    {"outcome": "matched", "values": ["cisco_ios", "{null}"]},
                ],
                "default_outcome": "other",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="route-9",
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(
            set(by_name["matched"].context.devices), {"ios-1", "missing-1"}
        )
        self.assertEqual(by_name["other"].context.devices, {})

    async def test_first_matching_route_wins(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "ios-1": _device("ios-1", network_driver="cisco_ios"),
            },
        )

        outcomes = await execute(
            config={
                "attribute_path": "network_driver",
                "routes": [
                    {"outcome": "primary", "values": ["cisco_ios", "ios"]},
                    {"outcome": "secondary", "values": ["cisco_ios"]},
                ],
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="route-5",
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["primary"].context.devices), ["ios-1"])
        self.assertEqual(by_name["secondary"].context.devices, {})

    async def test_routes_on_presence_of_parsed_cisco_aaa_servers(self) -> None:
        """A device parsed by parse-cisco-config exposes device.parsed under the
        "parsed" namespace, e.g. parsed.cisco_config.aaa_servers.servers — a list
        that can't be matched as a literal value, but can be routed on
        {exists}/{absent} to check whether any AAA server is configured at all."""
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "has-tacacs": _device(
                    "has-tacacs",
                    parsed={
                        "cisco_config": {
                            "aaa_servers": {
                                "servers": [
                                    {"name": "tacacs1", "protocol": "tacacs", "address": "10.0.0.5"}
                                ]
                            }
                        }
                    },
                ),
                "no-tacacs": _device(
                    "no-tacacs",
                    parsed={"cisco_config": {"aaa_servers": {"servers": []}}},
                ),
                "not-parsed": _device("not-parsed"),
            },
        )

        outcomes = await execute(
            config={
                "attribute_path": "parsed.cisco_config.aaa_servers.servers",
                "routes": [
                    {"outcome": "has-tacacs", "values": ["{exists}"]},
                    {"outcome": "no-tacacs", "values": ["{empty}", "{absent}"]},
                ],
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="route-10",
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["has-tacacs"].context.devices), ["has-tacacs"])
        self.assertEqual(
            set(by_name["no-tacacs"].context.devices), {"no-tacacs", "not-parsed"}
        )


if __name__ == "__main__":
    unittest.main()
