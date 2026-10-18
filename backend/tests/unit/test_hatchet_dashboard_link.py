"""The "Open in Hatchet" link: no credentials in it, and only for people who may see the engine."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from services.execution.run_service import RunService
from services.hatchet import hatchet_settings_service as settings_service


def _client(server_url: str = "http://engine:8080", tenant_id: str = "tenant-1") -> MagicMock:
    client = MagicMock()
    client.config.server_url = server_url
    client.config.tenant_id = tenant_id
    return client


class DashboardRunUrlTests(unittest.TestCase):
    def test_builds_the_run_link(self) -> None:
        with (
            patch.object(settings_service, "hatchet", _client()),
            patch.dict(os.environ, {"HATCHET_DASHBOARD_URL": "https://hatchet.example.com/"}),
        ):
            url = settings_service.dashboard_run_url("run-1")
        self.assertEqual(url, "https://hatchet.example.com/tenants/tenant-1/runs/run-1")

    def test_credentials_in_the_base_url_never_reach_the_link(self) -> None:
        with (
            patch.object(settings_service, "hatchet", _client()),
            patch.dict(
                os.environ,
                {"HATCHET_DASHBOARD_URL": "https://admin:hunter2@hatchet.example.com:8888/x"},
            ),
        ):
            url = settings_service.dashboard_run_url("run-1") or ""
            shown = settings_service._dashboard_base_url()
        for value in (url, shown):
            self.assertNotIn("hunter2", value)
            self.assertNotIn("admin", value)
            self.assertIn("hatchet.example.com:8888", value)

    def test_no_link_for_an_undispatched_run(self) -> None:
        with patch.object(settings_service, "hatchet", _client()):
            self.assertIsNone(settings_service.dashboard_run_url(None))


class RunLinkPermissionTests(unittest.TestCase):
    def _get_run(self, allowed: bool) -> tuple[MagicMock, MagicMock]:
        service = RunService(MagicMock())
        run = MagicMock(workflow_id=1, hatchet_run_id="run-1")
        response = MagicMock()
        with (
            patch.object(service.run_repo, "get_run_by_id", return_value=(run, "tester")),
            patch.object(service, "_assert_workflow_access"),
            patch.object(service, "_response", return_value=response),
            patch("services.auth.rbac_service.RBACService.has_permission", return_value=allowed),
            patch("services.execution.run_service.dashboard_run_url", return_value="http://link"),
        ):
            service.get_run(run_id=5, user_id=9)
        return service, response

    def test_operator_gets_the_link(self) -> None:
        _, response = self._get_run(allowed=True)
        response.model_copy.assert_called_once_with(update={"hatchet_dashboard_url": "http://link"})

    def test_other_run_viewers_do_not(self) -> None:
        _, response = self._get_run(allowed=False)
        response.model_copy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
