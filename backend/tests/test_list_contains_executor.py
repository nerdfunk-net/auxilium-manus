"""Tests for list-contains executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from workflow_steps.list_contains.executor import execute


def _device(
    device_id: str,
    *,
    parsed: dict | None = None,
    attribute_bags: dict | None = None,
) -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id,
        parsed=parsed or {},
        attribute_bags=attribute_bags or {},
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


_AAA_SERVERS = {
    "cisco_config": {
        "aaa_servers": {
            "servers": [
                {"name": "tacacs1", "protocol": "tacacs", "address": "10.0.0.5"},
                {"name": "tacacs2", "protocol": "tacacs", "address": "10.0.0.6"},
            ]
        }
    }
}

# Real cisco-config-parser output shape for two ACLs, one of which permits
# 172.16.9.100 — the exact scenario of "does ACL X permit source Y".
_ACCESS_LISTS_PARSED = {
    "cisco_config": {
        "access_lists": [
            {
                "name": "MGMT_100",
                "style": "named",
                "type": "standard",
                "entries": [
                    {
                        "action": "permit",
                        "source": "172.16.9.100",
                        "destination": None,
                        "sequence": "10",
                    }
                ],
            },
            {
                "name": "TRAFFIC_in",
                "style": "named",
                "type": "extended",
                "entries": [
                    {
                        "action": "permit",
                        "source": "192.168.178.240",
                        "destination": "192.168.0.2",
                        "sequence": "110",
                    }
                ],
            },
        ]
    }
}


class ListContainsExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_matches_on_field_within_list_of_objects(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"d1": _device("d1", parsed=_AAA_SERVERS)},
        )

        outcomes = await execute(
            config={
                "list_path": "parsed.cisco_config.aaa_servers.servers",
                "field": "address",
                "value": "10.0.0.5",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="lc-1",
        )

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["match"].context.devices), ["d1"])
        self.assertEqual(by_name["mismatch"].context.devices, {})
        self.assertEqual(by_name["failure"].context.devices, {})
        entry = by_name["match"].context.devices["d1"].parsed["lc-1.membership"]
        self.assertTrue(entry["matched"])
        self.assertEqual(entry["matched_item"]["name"], "tacacs1")
        self.assertIn(Capability.PARSED, by_name["match"].context.devices["d1"].capabilities)

    async def test_mismatch_when_value_not_in_list(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"d1": _device("d1", parsed=_AAA_SERVERS)},
        )

        outcomes = await execute(
            config={
                "list_path": "parsed.cisco_config.aaa_servers.servers",
                "field": "address",
                "value": "192.168.1.1",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="lc-1",
        )

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(by_name["match"].context.devices, {})
        self.assertEqual(list(by_name["mismatch"].context.devices), ["d1"])

    async def test_mismatch_when_list_is_empty(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "d1": _device(
                    "d1", parsed={"cisco_config": {"aaa_servers": {"servers": []}}}
                )
            },
        )

        outcomes = await execute(
            config={
                "list_path": "parsed.cisco_config.aaa_servers.servers",
                "field": "address",
                "value": "10.0.0.5",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="lc-1",
        )

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["mismatch"].context.devices), ["d1"])
        self.assertEqual(by_name["failure"].context.devices, {})

    async def test_matches_plain_scalar_list_without_field(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"d1": _device("d1", parsed={"cisco_config": {"vlans": [10, 20, 30]}})},
        )

        outcomes = await execute(
            config={
                "list_path": "parsed.cisco_config.vlans",
                "value": "20",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="lc-1",
        )

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["match"].context.devices), ["d1"])

    async def test_failure_when_list_path_not_populated(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"d1": _device("d1")},  # never parsed
        )

        outcomes = await execute(
            config={
                "list_path": "parsed.cisco_config.aaa_servers.servers",
                "field": "address",
                "value": "10.0.0.5",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="lc-1",
        )

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["failure"].context.devices), ["d1"])
        failed = by_name["failure"].context.devices["d1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[-1].code, "list_not_populated")

    async def test_failure_when_list_path_resolves_to_non_list(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"d1": _device("d1", parsed={"cisco_config": {"hostname": "router1"}})},
        )

        outcomes = await execute(
            config={
                "list_path": "parsed.cisco_config.hostname",
                "value": "router1",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="lc-1",
        )

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["failure"].context.devices), ["d1"])
        self.assertEqual(by_name["failure"].context.devices["d1"].errors[-1].code, "not_a_list")

    async def test_value_expression_resolves_per_device_attribute(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "d1": _device(
                    "d1",
                    parsed=_AAA_SERVERS,
                    attribute_bags={"custom": {"expected_tacacs_ip": "10.0.0.6"}},
                )
            },
        )

        outcomes = await execute(
            config={
                "list_path": "parsed.cisco_config.aaa_servers.servers",
                "field": "address",
                "value": "{custom.expected_tacacs_ip}",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="lc-1",
        )

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["match"].context.devices), ["d1"])
        entry = by_name["match"].context.devices["d1"].parsed["lc-1.membership"]
        self.assertEqual(entry["value"], "10.0.0.6")

    async def test_value_expression_falls_back_to_default(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"d1": _device("d1", parsed=_AAA_SERVERS)},
        )

        outcomes = await execute(
            config={
                "list_path": "parsed.cisco_config.aaa_servers.servers",
                "field": "address",
                "value": "{custom.expected_tacacs_ip | default('10.0.0.5')}",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="lc-1",
        )

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["match"].context.devices), ["d1"])

    async def test_failure_when_value_expression_resolves_to_nothing(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"d1": _device("d1", parsed=_AAA_SERVERS)},
        )

        outcomes = await execute(
            config={
                "list_path": "parsed.cisco_config.aaa_servers.servers",
                "field": "address",
                "value": "{custom.missing}",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="lc-1",
        )

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["failure"].context.devices), ["d1"])
        failed = by_name["failure"].context.devices["d1"]
        self.assertEqual(failed.errors[-1].code, "value_unresolved")

    async def test_case_insensitive_by_default_and_case_sensitive_opt_in(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "d1": _device(
                    "d1",
                    parsed={
                        "cisco_config": {
                            "aaa_servers": {"servers": [{"name": "TACACS1", "address": "10.0.0.5"}]}
                        }
                    },
                )
            },
        )

        insensitive = await execute(
            config={
                "list_path": "parsed.cisco_config.aaa_servers.servers",
                "field": "name",
                "value": "tacacs1",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="lc-1",
        )
        by_name = {o.name: o for o in insensitive}
        self.assertEqual(list(by_name["match"].context.devices), ["d1"])

        sensitive = await execute(
            config={
                "list_path": "parsed.cisco_config.aaa_servers.servers",
                "field": "name",
                "value": "tacacs1",
                "case_sensitive": True,
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="lc-1",
        )
        by_name_sensitive = {o.name: o for o in sensitive}
        self.assertEqual(list(by_name_sensitive["mismatch"].context.devices), ["d1"])

    async def test_multiple_devices_partitioned_across_buckets(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "match-dev": _device("match-dev", parsed=_AAA_SERVERS),
                "mismatch-dev": _device(
                    "mismatch-dev", parsed={"cisco_config": {"aaa_servers": {"servers": []}}}
                ),
                "failure-dev": _device("failure-dev"),
            },
        )

        outcomes = await execute(
            config={
                "list_path": "parsed.cisco_config.aaa_servers.servers",
                "field": "address",
                "value": "10.0.0.5",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="lc-1",
        )

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["match"].context.devices), ["match-dev"])
        self.assertEqual(list(by_name["mismatch"].context.devices), ["mismatch-dev"])
        self.assertEqual(list(by_name["failure"].context.devices), ["failure-dev"])
        counts = by_name["match"].context.metadata["lc-1.membership_counts"]
        self.assertEqual(counts, {"match": 1, "mismatch": 1, "failure": 1})

    async def test_no_devices_returns_empty_outcomes(self) -> None:
        run = MagicMock()
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={})

        outcomes = await execute(
            config={"list_path": "parsed.cisco_config.vlans", "value": "10"},
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="lc-1",
        )

        self.assertEqual({o.name for o in outcomes}, {"match", "mismatch", "failure"})
        for outcome in outcomes:
            self.assertEqual(outcome.context.devices, {})

    async def test_missing_list_path_raises_value_error(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1", workflow_id="wf-1", devices={"d1": _device("d1")}
        )

        with self.assertRaises(ValueError):
            await execute(
                config={"value": "10.0.0.5"},
                context=context,
                run=run,
                artifact_service=MagicMock(),
                node_id="lc-1",
            )

    async def test_missing_value_raises_value_error(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1", workflow_id="wf-1", devices={"d1": _device("d1")}
        )

        with self.assertRaises(ValueError):
            await execute(
                config={"list_path": "parsed.cisco_config.vlans"},
                context=context,
                run=run,
                artifact_service=MagicMock(),
                node_id="lc-1",
            )

    async def test_acl_permits_source_via_filter_segment(self) -> None:
        """The motivating end-to-end case: does ACL MGMT_100 permit source
        172.16.9.100? list_path filters access_lists down to the one named
        MGMT_100 and reaches into its entries list in one path."""
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"d1": _device("d1", parsed=_ACCESS_LISTS_PARSED)},
        )

        outcomes = await execute(
            config={
                "list_path": "parsed.cisco_config.access_lists[name=MGMT_100].entries",
                "field": "source",
                "value": "172.16.9.100",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="lc-1",
        )

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["match"].context.devices), ["d1"])
        entry = by_name["match"].context.devices["d1"].parsed["lc-1.membership"]
        self.assertEqual(entry["matched_item"]["action"], "permit")

    async def test_acl_does_not_permit_source_mismatches(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"d1": _device("d1", parsed=_ACCESS_LISTS_PARSED)},
        )

        outcomes = await execute(
            config={
                "list_path": "parsed.cisco_config.access_lists[name=MGMT_100].entries",
                "field": "source",
                "value": "10.10.10.10",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="lc-1",
        )

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["mismatch"].context.devices), ["d1"])

    async def test_acl_name_not_found_fails_the_device(self) -> None:
        run = MagicMock()
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={"d1": _device("d1", parsed=_ACCESS_LISTS_PARSED)},
        )

        outcomes = await execute(
            config={
                "list_path": "parsed.cisco_config.access_lists[name=NOT_A_REAL_ACL].entries",
                "field": "source",
                "value": "172.16.9.100",
            },
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="lc-1",
        )

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["failure"].context.devices), ["d1"])
        failed = by_name["failure"].context.devices["d1"]
        self.assertEqual(failed.errors[-1].code, "list_not_populated")


if __name__ == "__main__":
    unittest.main()
