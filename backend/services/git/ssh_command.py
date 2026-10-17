from __future__ import annotations

from pathlib import Path

from core.config import settings

_KNOWN_HOSTS_REL = Path("ssh") / "known_hosts"


def git_known_hosts_path() -> Path:
    directory = settings.data_directory / "ssh"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = settings.data_directory / _KNOWN_HOSTS_REL
    if not path.exists():
        path.touch(mode=0o600)
    return path


def build_git_ssh_command(ssh_key_path: str) -> str:
    known_hosts = git_known_hosts_path()
    return (
        f'ssh -i "{ssh_key_path}" -o IdentitiesOnly=yes '
        f'-o StrictHostKeyChecking=accept-new '
        f'-o UserKnownHostsFile="{known_hosts}"'
    )
