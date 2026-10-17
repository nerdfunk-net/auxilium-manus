"""Tests for the Catalyst Center version label (display only)."""

from __future__ import annotations

import pytest

from services.catalyst_center.common.version import installed_version_label

# Captured from the live DevNet sandbox (sandboxdnac2): ``installedVersion`` is the platform
# build, NOT a product release such as 2.3.7.x.
SANDBOX_RELEASE_PAYLOAD = {
    "version": "2.0",
    "response": {
        "name": "uber-dnac",
        "displayName": "Cisco Catalyst Center",
        "installedVersion": "3.722.75335",
        "systemVersion": "2.7.72",
        "packages": ["sda:2.722.65411"],
    },
}


class TestInstalledVersionLabel:
    def test_label_reports_the_controller_string_verbatim(self):
        assert installed_version_label(SANDBOX_RELEASE_PAYLOAD) == "3.722.75335"

    def test_label_reads_installed_version(self):
        payload = {"response": {"installedVersion": "2.3.7.9-70050"}}
        assert installed_version_label(payload) == "2.3.7.9-70050"

    def test_label_falls_back_to_version_key(self):
        assert installed_version_label({"response": {"version": "3.1.6"}}) == "3.1.6"

    @pytest.mark.parametrize("payload", [{}, {"response": {}}, {"response": "x"}, [], None])
    def test_label_is_none_without_a_version(self, payload):
        assert installed_version_label(payload) is None
