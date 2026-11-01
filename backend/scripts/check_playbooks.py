#!/usr/bin/env python3
"""Validate the assistant's playbook files without starting the application.

Checks the built-in playbooks (``services/ai_assistant/knowledge/playbooks``) and the local ones
(``${DATA_DIRECTORY}/ai/playbooks``, or the directory given with ``--dir``) with the same rules the
application applies when it loads them (doc/AI_TOOL_CHAIN.md §25.6): front matter fields, the tools
named exist on the ``general`` surface, read-only, no configuration commands, size limits.

Exit status ``1`` if any file is invalid. Usage, from ``backend/``::

    python scripts/check_playbooks.py [--dir PATH]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.ai_assistant.playbooks import load_playbooks, shared_with_everyone  # noqa: E402
from services.ai_assistant.tools.playbook_tools import known_general_tool_names  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dir", type=Path, default=None, help="local playbook directory (default: the data volume)"
    )
    args = parser.parse_args(argv)

    result = load_playbooks(known_tools=known_general_tool_names(), local_dir=args.dir)
    for playbook in result.playbooks:
        print(f"[ok] {playbook.source:7} {playbook.name} (class {playbook.data_class})")
    for playbook in result.playbooks:
        if shared_with_everyone(playbook):
            print(
                f"[note] {playbook.name}: local class A, so its text goes to every user "
                "(and the provider) without the inventory opt-in"
            )
    for entry in result.invalid:
        print(f"[FAIL] {entry.source} {entry.file}: {entry.reason}")
    if result.invalid:
        return 1
    print(f"[OK] {len(result.playbooks)} playbook(s) valid")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
