"""SSH command builder must never disable host-key checking.

Regression coverage for the SSH MITM gap where git SSH operations used
StrictHostKeyChecking=no / UserKnownHostsFile=/dev/null.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.git import auth as git_auth_module
from services.git import connection as git_connection_module
from services.git.ssh_command import build_git_ssh_command


class BuildGitSshCommandTests(unittest.TestCase):
    def test_uses_accept_new_and_known_hosts_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("services.git.ssh_command.settings.data_directory", Path(tmp)):
                command = build_git_ssh_command("/tmp/id_rsa")

        self.assertIn("StrictHostKeyChecking=accept-new", command)
        self.assertIn("UserKnownHostsFile=", command)
        self.assertNotIn("StrictHostKeyChecking=no", command)
        self.assertNotIn("/dev/null", command)

    def test_creates_known_hosts_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            with patch("services.git.ssh_command.settings.data_directory", data_dir):
                build_git_ssh_command("/tmp/id_rsa")

            known_hosts = data_dir / "ssh" / "known_hosts"
            self.assertTrue(known_hosts.exists())


class NoHostKeyBypassInSourceTests(unittest.TestCase):
    def test_connection_and_auth_modules_do_not_disable_host_key_checking(self) -> None:
        for module in (git_connection_module, git_auth_module):
            source = Path(module.__file__).read_text(encoding="utf-8")
            self.assertNotIn("StrictHostKeyChecking=no", source)
            self.assertNotIn("UserKnownHostsFile=/dev/null", source)


if __name__ == "__main__":
    unittest.main()
