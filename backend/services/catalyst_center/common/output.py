"""Clean raw Catalyst Center command-runner output.

The command runner returns terminal text: the echoed command first and the device prompt
last (``show clock\n*15:22:13.553 UTC ...\nsw1#``). Steps store and parse the output
alone, so both are stripped.
"""

from __future__ import annotations

import re

# ``sw1#``, ``sw1>``, ``sw1(config-if)#``, ``user@host:path#`` -- a lone prompt line.
_PROMPT = r"[\w.\-/@:]+(?:\([\w.\-/]+\))?[#>]"
_PROMPT_LINE = re.compile(rf"^{_PROMPT}\s*$")


def _is_echo(first_line: str, command: str) -> bool:
    line = first_line.strip()
    target = command.strip()
    if line == target:
        return True
    if not line.endswith(target):
        return False
    return _PROMPT_LINE.match(line[: len(line) - len(target)]) is not None


def clean_command_output(command: str, output: str) -> str:
    """Return ``output`` without the echoed ``command`` line and the trailing prompt."""
    lines = output.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and _is_echo(lines[0], command):
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and _PROMPT_LINE.match(lines[-1].strip()):
        lines.pop()
    return "\n".join(lines).strip("\n")
