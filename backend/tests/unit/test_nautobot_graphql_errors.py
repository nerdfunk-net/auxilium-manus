"""C7-03: a GraphQL error payload goes to the log, never into a raised (persisted) message."""

from __future__ import annotations

import logging
import unittest
from unittest.mock import AsyncMock, MagicMock

from services.nautobot.common.exceptions import NautobotAPIError
from services.nautobot.common.utils import graphql_errors_summary
from services.nautobot.managers.vlan_manager import _query_vlans

_PAYLOAD = [{"message": "Cannot query field 'secret_token' on Device", "path": ["device"]}]


class GraphqlErrorSummaryTests(unittest.TestCase):
    def test_summary_has_no_payload_and_payload_is_logged(self) -> None:
        with self.assertLogs("services.nautobot.common.utils", level=logging.ERROR) as logs:
            text = graphql_errors_summary(_PAYLOAD, "while testing")
        self.assertNotIn("secret_token", text)
        self.assertIn("1 GraphQL error(s) while testing", text)
        self.assertIn("secret_token", "\n".join(logs.output))


class VlanQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_vlan_lookup_error_does_not_carry_the_payload(self) -> None:
        nautobot = MagicMock()
        nautobot.graphql_query = AsyncMock(return_value={"errors": _PAYLOAD})
        with self.assertRaises(NautobotAPIError) as ctx:
            await _query_vlans(nautobot, 100, None)
        self.assertNotIn("secret_token", str(ctx.exception))
        self.assertIn("VLAN 100", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
