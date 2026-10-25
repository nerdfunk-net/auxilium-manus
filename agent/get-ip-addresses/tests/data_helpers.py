"""Fixtures for the data-source tests: the sample CSV, its mapping and a throw-away git repo."""

from __future__ import annotations

import subprocess  # noqa: S404
from pathlib import Path
from typing import Any

SAMPLE_CSV = (
    "name;interface_name;interface_address;is_primary;namespace\n"
    "device-1;eth0;10.0.0.2/24;true;black\n"
    "device-1;eth1;192.168.181.10/24;false;Global\n"
)

RAW_MAPPING: list[dict[str, str]] = [
    {"source": "name", "target": "name"},
    {"source": "interface_name", "target": "interfaces.name"},
    {"source": "interface_address", "target": "interfaces.ip_addresses.address"},
    {"source": "namespace", "target": "interfaces.ip_addresses.parent.namespace.name"},
    {"source": "is_primary", "target": "_is_primary"},
]


def raw_config(url: str, checkout: str = "repo", **git_overrides: Any) -> dict[str, Any]:
    return {
        "git": {"url": url, "branch": "main", "checkout_dir": checkout, **git_overrides},
        "source": {"directory": "ips", "filename_pattern": "*.csv", "csv_delimiter": ";"},
        "mapping": RAW_MAPPING,
    }


def git(cwd: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def make_origin(root: Path, files: dict[str, str] | None = None) -> Path:
    """A repository on branch ``main`` holding ``files`` (default: ips/devices.csv)."""
    origin = root / "origin"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "main")
    commit(origin, files or {"ips/devices.csv": SAMPLE_CSV}, "initial")
    return origin


def commit(origin: Path, files: dict[str, str], message: str) -> None:
    for name, content in files.items():
        path = origin / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git(origin, "add", "-A")
    git(origin, "commit", "-q", "-m", message)
