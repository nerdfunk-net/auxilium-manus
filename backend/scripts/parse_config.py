#!/usr/bin/env python3
"""Parse a local Cisco config file with cisco_config_parser and print JSON.

Uses the same helper as the ``parse-cisco-config`` workflow step
(``workflow_steps.common.cisco_config_parsing.parse_cisco_config_text``).

Usage (from ``backend/``, with the project venv active)::

    ../.venv/bin/python scripts/parse_config.py /path/to/running-config.txt
    ../.venv/bin/python scripts/parse_config.py config.txt --platform IOS
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from workflow_steps.common.cisco_config_parsing import parse_cisco_config_text  # noqa: E402

_PLATFORM_CHOICES = ("IOS", "NXOS", "XR")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Parse a local Cisco config file and print the parsed model as JSON.",
    )
    parser.add_argument(
        "config_file",
        type=Path,
        help="Path to a Cisco running/startup config text file",
    )
    parser.add_argument(
        "--platform",
        choices=_PLATFORM_CHOICES,
        default=None,
        help="Optional platform hint passed to cisco_config_parser (default: auto-detect)",
    )
    args = parser.parse_args(argv)

    path: Path = args.config_file
    if not path.is_file():
        print(f"error: config file not found: {path}", file=sys.stderr)
        return 1

    content = path.read_text(encoding="utf-8", errors="replace")
    parsed = parse_cisco_config_text(content, args.platform)
    json.dump(parsed, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
