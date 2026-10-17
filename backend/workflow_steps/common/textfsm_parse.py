"""TextFSM (ntc-templates) parsing of raw CLI output into the shared ``{parsed, error}`` shape.

``run-command`` lets Netmiko parse inline; steps that get their text some other way (for
example the Catalyst Center command runner) call this instead. Both land the result at
``parsed.<parsed_output_key>.<command>`` so a downstream step never needs to know which
path produced it. Parsing is non-fatal per command.
"""

from __future__ import annotations

from typing import Any

from netmiko.utilities import get_structured_data_textfsm

# Catalyst Center ``network_driver`` values are Netmiko device types, which is what the
# ntc-templates index keys on (``cisco_xe`` falls back to ``cisco_ios`` inside Netmiko).


def parse_with_textfsm(output: str, *, command: str, platform: str | None) -> dict[str, Any]:
    """Return ``{"parsed": rows, "error": None}`` or ``{"parsed": None, "error": reason}``."""
    if not platform:
        return {
            "parsed": None,
            "error": "TextFSM needs a network driver; the device has none "
            "(set network_driver_override)",
        }
    try:
        rows = get_structured_data_textfsm(output, platform=platform, command=command)
    except Exception as exc:  # TextFSM raises assorted errors on a template/output mismatch
        return {"parsed": None, "error": f"TextFSM failed: {type(exc).__name__}"}
    if not isinstance(rows, list):
        # Netmiko hands back the raw text when no template matches the command.
        return {
            "parsed": None,
            "error": "TextFSM did not match this command's output (no template found)",
        }
    return {"parsed": rows, "error": None}
