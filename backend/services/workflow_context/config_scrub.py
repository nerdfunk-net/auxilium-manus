"""Best-effort masking of secret operands in device configuration text (C5R-05).

Used where configuration text is attached to something a person reads (``log-attributes``). The
keyword stays so the line is still recognisable (``enable secret 9 <redacted>``). It is a list of
well-known IOS/NX-OS/Junos-like spellings, not a guarantee: the configuration artifact itself is
stored verbatim.
"""

from __future__ import annotations

import re

REDACTED = "<redacted>"

_KEYWORDS = (
    r"enable\s+(?:secret|password)",
    r"username\s+\S+(?:\s+\S+)*?\s+(?:secret|password)",
    r"snmp-server\s+community",
    r"(?:tacacs|radius)-server(?:\s+host\s+\S+)?\s+key",
    r"crypto\s+isakmp\s+key",
    r"pre-shared-key(?:\s+(?:local|remote))?",
    r"key-string",
    r"key(?!\s+(?:chain|config-key)\b)",
    r"password",
    r"secret",
)

# <keyword> [<encryption type 0-9>] <operand>
_LINE = re.compile(
    r"^(?P<head>[ \t]*(?:" + "|".join(_KEYWORDS) + r"))(?P<enc>[ \t]+\d)?[ \t]+(?P<val>\S+)",
    re.IGNORECASE | re.MULTILINE,
)

# snmp-server host <addr> [traps|informs] [version <v> [auth|noauth|priv]] <community>
_SNMP_HOST = re.compile(
    r"^(?P<head>[ \t]*snmp-server[ \t]+host[ \t]+\S+[ \t]+"
    r"(?:(?:traps|informs|version[ \t]+\S+(?:[ \t]+(?:auth|noauth|priv))?)[ \t]+)*)(?P<val>\S+)",
    re.IGNORECASE | re.MULTILINE,
)


def scrub_config_text(text: str) -> str:
    """Mask the secret operand of well-known secret-bearing configuration lines."""
    text = _SNMP_HOST.sub(lambda m: f"{m.group('head')}{REDACTED}", text)
    return _LINE.sub(lambda m: f"{m.group('head')}{m.group('enc') or ''} {REDACTED}", text)
