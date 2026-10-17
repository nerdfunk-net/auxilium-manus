"""Tests for route-on-attribute executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from core.crypto import EncryptionService
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    WorkflowContext,
)
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.route_on_attribute.executor import execute

_ENC = EncryptionService("test-secret-key-for-route-on-attribute")


def _device(
    device_id: str,
    *,
    network_driver: str | None = None,
    attribute_bags: dict | None = None,
    parsed: dict | None = None,
    errors: list[DeviceError] | None = None,
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
        errors=errors or [],
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
            device_sessions=MagicMock(),
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
            device_sessions=MagicMock(),
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
            device_sessions=MagicMock(),
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(by_name["ios"].context.devices, {})
        self.assertEqual(list(by_name["other"].context.devices), ["junos-1"])

    async def test_unmatched_device_leaves_through_failure_and_others_route(self) -> None:
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "ios-1": _device("ios-1", network_driver="cisco_ios"),
                "ios-2": _device("ios-2", network_driver="cisco_ios"),
                "junos-1": _device("junos-1", network_driver="junos"),
            },
        )

        outcomes = await execute(
            config={
                "attribute_path": "network_driver",
                "routes": [{"outcome": "ios", "values": ["cisco_ios"]}],
            },
            context=context,
            run=MagicMock(),
            artifact_service=MagicMock(),
            node_id="route-4",
            device_sessions=MagicMock(),
        )

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(sorted(by_name["ios"].context.devices), ["ios-1", "ios-2"])
        failed = by_name["failure"].context.devices["junos-1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[-1].code, "no_route_matched")

    async def test_reserved_route_name_is_rejected(self) -> None:
        for reserved in ("success", "failure"):
            with self.assertRaises(ValueError):
                await execute(
                    config={
                        "attribute_path": "network_driver",
                        "routes": [{"outcome": reserved, "values": ["x"]}],
                    },
                    context=WorkflowContext(
                        run_id="r",
                        workflow_id="w",
                        devices={"d": _device("d", network_driver="x")},
                    ),
                    run=MagicMock(),
                    artifact_service=MagicMock(),
                    node_id="route-5",
                    device_sessions=MagicMock(),
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
                    {"outcome": "has-key", "values": ["{:exists()}"]},
                    {
                        "outcome": "no-key",
                        "values": ["{:isAbsent()}", "{:isNull()}", "{:isEmpty()}"],
                    },
                ],
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="route-6",
            device_sessions=MagicMock(),
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["has-key"].context.devices), ["has-key"])
        self.assertEqual(list(by_name["no-key"].context.devices), ["no-key"])

    async def test_routes_on_sealed_secret_without_decrypting(self) -> None:
        """A sealed TACACS+ key must still classify as {:exists()} — route-on-attribute
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
                    {"outcome": "has-key", "values": ["{:exists()}"]},
                    {
                        "outcome": "no-key",
                        "values": ["{:isAbsent()}", "{:isNull()}", "{:isEmpty()}"],
                    },
                ],
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="route-6b",
            device_sessions=MagicMock(),
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
                "null-1": _device("null-1", attribute_bags={"tacacs": {"shared_secret": None}}),
            },
        )

        outcomes = await execute(
            config={
                "attribute_path": "tacacs.shared_secret",
                "routes": [
                    {"outcome": "null-route", "values": ["{:isNull()}"]},
                    {"outcome": "absent-route", "values": ["{:isAbsent()}"]},
                ],
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="route-7",
            device_sessions=MagicMock(),
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
                "empty-1": _device("empty-1", attribute_bags={"tacacs": {"shared_secret": "   "}}),
            },
        )

        outcomes = await execute(
            config={
                "attribute_path": "tacacs.shared_secret",
                "routes": [
                    {"outcome": "empty-route", "values": ["{:isEmpty()}"]},
                    {"outcome": "exists-route", "values": ["{:exists()}"]},
                ],
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="route-8",
            device_sessions=MagicMock(),
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
                    {"outcome": "matched", "values": ["cisco_ios", "{:isNull()}"]},
                ],
                "default_outcome": "other",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="route-9",
            device_sessions=MagicMock(),
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(set(by_name["matched"].context.devices), {"ios-1", "missing-1"})
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
            device_sessions=MagicMock(),
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["primary"].context.devices), ["ios-1"])
        self.assertEqual(by_name["secondary"].context.devices, {})

    async def test_routes_on_presence_of_parsed_cisco_aaa_servers(self) -> None:
        """A device parsed by parse-cisco-config exposes device.parsed under the
        "parsed" namespace, e.g. parsed.cisco_config.running.aaa_servers.servers —
        a list that can't be matched as a literal value, but can be routed on
        {:exists()}/{:isAbsent()} to check whether any AAA server is configured at all."""
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "has-tacacs": _device(
                    "has-tacacs",
                    parsed={
                        "cisco_config": {
                            "running": {
                                "aaa_servers": {
                                    "servers": [
                                        {
                                            "name": "tacacs1",
                                            "protocol": "tacacs",
                                            "address": "10.0.0.5",
                                        }
                                    ]
                                }
                            },
                            "startup": None,
                        }
                    },
                ),
                "no-tacacs": _device(
                    "no-tacacs",
                    parsed={
                        "cisco_config": {
                            "running": {"aaa_servers": {"servers": []}},
                            "startup": None,
                        }
                    },
                ),
                "not-parsed": _device("not-parsed"),
            },
        )

        outcomes = await execute(
            config={
                "attribute_path": "parsed.cisco_config.running.aaa_servers.servers",
                "routes": [
                    {"outcome": "has-tacacs", "values": ["{:exists()}"]},
                    {"outcome": "no-tacacs", "values": ["{:isEmpty()}", "{:isAbsent()}"]},
                ],
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="route-10",
            device_sessions=MagicMock(),
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["has-tacacs"].context.devices), ["has-tacacs"])
        self.assertEqual(set(by_name["no-tacacs"].context.devices), {"no-tacacs", "not-parsed"})

    async def test_routes_by_error_code_from_most_recent_accumulated_error(self) -> None:
        """A failure outcome wired into this step should be routable by why the
        upstream step failed (e.g. add-to-nautobot's device_already_exists),
        not just whether it failed."""
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "dup-1": _device(
                    "dup-1",
                    errors=[
                        DeviceError(
                            node_id="add-1",
                            step_id="add-to-nautobot",
                            code="device_already_exists",
                            message="A device named 'dup-1' already exists",
                        )
                    ],
                ),
                "other-1": _device(
                    "other-1",
                    errors=[
                        DeviceError(
                            node_id="add-1",
                            step_id="add-to-nautobot",
                            code="missing_required_field",
                            message="Required field(s) could not be resolved: role",
                        )
                    ],
                ),
                "no-error-1": _device("no-error-1"),
            },
        )

        outcomes = await execute(
            config={
                "attribute_path": "error.code",
                "routes": [
                    {"outcome": "update-existing", "values": ["device_already_exists"]},
                ],
                "default_outcome": "stop",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="route-11",
            device_sessions=MagicMock(),
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["update-existing"].context.devices), ["dup-1"])
        self.assertEqual(set(by_name["stop"].context.devices), {"other-1", "no-error-1"})

    async def test_error_namespace_resolves_absent_with_no_accumulated_errors(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"clean-1": _device("clean-1")},
        )

        outcomes = await execute(
            config={
                "attribute_path": "error.code",
                "routes": [{"outcome": "matched", "values": ["{:exists()}"]}],
                "default_outcome": "no-error",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="route-12",
            device_sessions=MagicMock(),
        )

        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(by_name["matched"].context.devices, {})
        self.assertEqual(list(by_name["no-error"].context.devices), ["clean-1"])


async def _route(config: dict, devices: dict[str, DeviceContext]) -> dict:
    outcomes = await execute(
        config=config,
        context=WorkflowContext(run_id="run-1", workflow_id="wf-1", devices=devices),
        run=MagicMock(),
        artifact_service=MagicMock(),
        node_id="route-x",
        device_sessions=MagicMock(),
    )
    return {outcome.name: sorted(outcome.context.devices) for outcome in outcomes}


class RouteOnAttributeExpressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_expression_with_its_own_key_ignores_attribute_path(self) -> None:
        devices = {
            "big": _device("big", attribute_bags={"custom": {"value": "42"}}),
            "small": _device("small", attribute_bags={"custom": {"value": "3"}}),
        }
        routed = await _route(
            {
                "attribute_path": "device.network_driver",
                "routes": [{"outcome": "high", "values": ["{custom.value:gt(10)}"]}],
                "default_outcome": "low",
            },
            devices,
        )
        self.assertEqual(routed, {"high": ["big"], "low": ["small"]})

    async def test_expression_without_key_uses_attribute_path(self) -> None:
        devices = {
            "lab": _device("lab", network_driver="Cisco_IOS"),
            "prod": _device("prod", network_driver="arista_eos"),
        }
        routed = await _route(
            {
                "attribute_path": "device.network_driver",
                "routes": [{"outcome": "cisco", "values": ["{:startsWith('cisco')}"]}],
                "default_outcome": "other",
            },
            devices,
        )
        # startsWith is case sensitive and case_sensitive only governs plain values.
        self.assertEqual(routed, {"cisco": [], "other": ["lab", "prod"]})

    async def test_commas_inside_an_expression_survive_a_string_values_field(self) -> None:
        devices = {"a": _device("a", attribute_bags={"custom": {"v": "y"}})}
        routed = await _route(
            {
                "attribute_path": "custom.v",
                "routes": [{"outcome": "hit", "values": "nope, {:in('x','y')}"}],
                "default_outcome": "miss",
            },
            devices,
        )
        self.assertEqual(routed, {"hit": ["a"], "miss": []})

    async def test_literal_and_expression_values_mix_first_match_wins(self) -> None:
        devices = {"a": _device("a", network_driver="cisco_ios")}
        routed = await _route(
            {
                "attribute_path": "device.network_driver",
                "routes": [
                    {"outcome": "first", "values": ["{:equals('x')}", "cisco_ios"]},
                    {"outcome": "second", "values": ["{:exists()}"]},
                ],
            },
            devices,
        )
        self.assertEqual(routed, {"first": ["a"], "second": []})

    async def test_regex_route_uses_the_isolated_runner(self) -> None:
        devices = {
            "sw1": _device("sw1"),
            "rtr1": _device("rtr1"),
        }
        routed = await _route(
            {
                "attribute_path": "device.name",
                "routes": [{"outcome": "switch", "values": [r"{:matches('sw\d+')}"]}],
                "default_outcome": "other",
            },
            devices,
        )
        self.assertEqual(routed, {"switch": ["sw1"], "other": ["rtr1"]})

    async def test_regex_combined_with_other_conditions(self) -> None:
        devices = {
            "sw1": _device("sw1", attribute_bags={"custom": {"n": "5"}}),
            "sw2": _device("sw2", attribute_bags={"custom": {"n": "50"}}),
        }
        routed = await _route(
            {
                "attribute_path": "device.name",
                "routes": [
                    {
                        "outcome": "big_switch",
                        "values": ["{:matches('sw.*'):and({custom.n:gt(10)})}"],
                    }
                ],
                "default_outcome": "other",
            },
            devices,
        )
        self.assertEqual(routed, {"big_switch": ["sw2"], "other": ["sw1"]})

    async def test_negated_regex_in_an_earlier_route_does_not_hide_a_later_regex_route(
        self,
    ) -> None:
        """EL_REVIEW #1: `matches(..):not()` is true while its regex is unanswered; routing must
        still ask the later route's regex instead of stopping at the false hit."""
        devices = {
            "prod-edge-1": _device("prod-edge-1", attribute_bags={"custom": {"role": "edge"}}),
            "lab-core-1": _device("lab-core-1", attribute_bags={"custom": {"role": "spine"}}),
        }
        for first in ("{:matches('lab-.*'):not()}", "{:matches('lab-.*'):equals(false)}"):
            routed = await _route(
                {
                    "attribute_path": "device.name",
                    "routes": [
                        {"outcome": "non_lab", "values": [first]},
                        {"outcome": "spine", "values": ["{custom.role:matches('spine')}"]},
                    ],
                    "default_outcome": "other",
                },
                devices,
            )
            self.assertEqual(
                routed,
                {"non_lab": ["prod-edge-1"], "spine": ["lab-core-1"], "other": []},
                first,
            )

    async def test_a_regex_built_from_another_regex_result_is_resolved(self) -> None:
        devices = {"lab-core-1": _device("lab-core-1"), "prod-1": _device("prod-1")}
        routed = await _route(
            {
                "attribute_path": "device.name",
                "routes": [
                    {
                        "outcome": "hit",
                        "values": ["{:append({:matches('lab-.*')}):find('1true')}"],
                    }
                ],
                "default_outcome": "other",
            },
            devices,
        )
        self.assertEqual(routed, {"hit": ["lab-core-1"], "other": ["prod-1"]})

    @staticmethod
    def _stacked_regex_expression(levels: int) -> str:
        """Level k matches a text that contains the answers of levels 1..k-1, so it can only be
        asked after they were answered: ``levels`` rounds of questions."""
        stacked = ["{:matches('.*')}"]
        for _ in range(levels - 1):
            appended = ":".join(f"append({inner})" for inner in stacked)
            stacked.append("{:" + appended + ":matches('.*')}")
        return stacked[-1]

    async def test_stacked_regex_chain_within_the_cap_is_resolved(self) -> None:
        routed = await _route(
            {
                "attribute_path": "device.name",
                "routes": [{"outcome": "x", "values": [self._stacked_regex_expression(3)]}],
                "default_outcome": "other",
            },
            {"a": _device("a")},
        )
        self.assertEqual(routed, {"x": ["a"], "other": []})

    async def test_regex_chain_deeper_than_the_cap_is_a_step_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "levels deep"):
            await _route(
                {
                    "attribute_path": "device.name",
                    "routes": [{"outcome": "x", "values": [self._stacked_regex_expression(7)]}],
                },
                {"a": _device("a")},
            )

    async def test_invalid_regex_fails_that_device_only_without_echoing_it(self) -> None:
        devices = {
            "bad": _device("bad", attribute_bags={"custom": {"pat": "("}}),
            "good": _device("good", attribute_bags={"custom": {"pat": "go+d"}}),
        }
        outcomes = await execute(
            config={
                "attribute_path": "device.name",
                "routes": [{"outcome": "hit", "values": ["{:matches({custom.pat})}"]}],
                "default_outcome": "other",
            },
            context=WorkflowContext(run_id="run-1", workflow_id="wf-1", devices=devices),
            run=MagicMock(),
            artifact_service=MagicMock(),
            node_id="route-x",
            device_sessions=MagicMock(),
        )
        by_name = {outcome.name: outcome for outcome in outcomes}
        self.assertEqual(list(by_name["hit"].context.devices), ["good"])
        self.assertEqual(list(by_name["failure"].context.devices), ["bad"])
        error = by_name["failure"].context.devices["bad"].errors[-1]
        self.assertEqual(error.code, "invalid_regular_expression")
        self.assertNotIn("(", error.message)
        self.assertNotIn("bad", error.message)

    async def test_find_with_an_empty_argument_does_not_match_everything(self) -> None:
        routed = await _route(
            {
                "attribute_path": "device.name",
                "routes": [{"outcome": "hit", "values": ["{:find({custom.p})}"]}],
                "default_outcome": "other",
            },
            {"a": _device("a", attribute_bags={"custom": {"p": "x"}})},
        )
        # An absent/empty pattern argument is no value: the predicate is false, not "matches all".
        self.assertEqual(routed, {"hit": [], "other": ["a"]})

    async def test_old_token_syntax_is_rejected_with_a_hint(self) -> None:
        with self.assertRaisesRegex(ValueError, r"\{:exists\(\)\}"):
            await _route(
                {
                    "attribute_path": "device.name",
                    "routes": [{"outcome": "x", "values": ["{exists}"]}],
                },
                {"a": _device("a")},
            )

    async def test_old_token_with_spaces_is_rejected_too(self) -> None:
        with self.assertRaisesRegex(ValueError, r"\{:exists\(\)\}"):
            await _route(
                {
                    "attribute_path": "device.name",
                    "routes": [{"outcome": "x", "values": ["{ exists }"]}],
                },
                {"a": _device("a")},
            )

    async def test_malformed_expression_fails_before_any_routing(self) -> None:
        with self.assertRaisesRegex(ValueError, "routes\\[0\\]"):
            await _route(
                {
                    "attribute_path": "device.name",
                    "routes": [{"outcome": "x", "values": ["{:bogus()}"]}],
                },
                {"a": _device("a")},
            )


if __name__ == "__main__":
    unittest.main()
