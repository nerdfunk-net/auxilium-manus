#!/usr/bin/env python3
"""Parse a local Cisco config with ConfigParser and print all model keys/values.

Follows the cisco_config_parser documentation style::

    model = parser.parse()
    model.keys()
    model["hostname"]
    model["routing"]["bgp"][0]["router_id"]

Usage (from ``backend/``, with the project venv active)::

    ../.venv/bin/python scripts/parse_config_keys.py /path/to/running-config.txt
    ../.venv/bin/python scripts/parse_config_keys.py config.txt --platform IOS
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cisco_config_parser import ConfigParser

_PLATFORM_CHOICES = ("IOS", "NXOS", "XR")


def main(argv: list[str] | None = None) -> int:
    arg_parser = argparse.ArgumentParser(
        description=(
            "Parse a local Cisco config with ConfigParser and print every "
            "top-level key with its value."
        ),
    )
    arg_parser.add_argument(
        "config_file",
        type=Path,
        help="Path to a Cisco running/startup config text file",
    )
    arg_parser.add_argument(
        "--platform",
        choices=_PLATFORM_CHOICES,
        default=None,
        help="Optional platform hint passed to ConfigParser (default: auto-detect)",
    )
    args = arg_parser.parse_args(argv)

    path: Path = args.config_file
    if not path.is_file():
        print(f"error: config file not found: {path}", file=sys.stderr)
        return 1

    content = path.read_text(encoding="utf-8", errors="replace")
    parser = ConfigParser(content, platform=args.platform)
    model = parser.parse()

    print("model.keys()")
    print(list(model.keys()))
    print()

    for key in model.keys():
        print(f'model[{key!r}]')
        print(json.dumps(model[key], indent=2, default=str))
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
