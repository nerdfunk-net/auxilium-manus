"""Validation of the per-repository device-config path templates.

A ``device_configs`` repository may carry two templates (``config_path_running`` and
``config_path_startup``) that say where a device's backed-up configuration lives, in the same
placeholder language as the ``read-config`` step, for example
``{nautobot.location.name}/{device.name}.running.cfg``. The assistant builds the path from the
template in code; the model never supplies one (doc/plans/AI_CONFIG_FROM_GIT.md).
"""

from __future__ import annotations

import re

MAX_TEMPLATE_CHARS = 500
# ``git`` and ``custom`` exist in workflows (filled by get-git-devices), but the assistant reader
# does not run that step, so they would never resolve here and are not accepted.
ALLOWED_NAMESPACES = frozenset({"device", "nautobot", "run"})
# At least one of these must appear, otherwise every device maps to one file.
_PER_DEVICE_PREFIXES = ("device.", "nautobot.")
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_PLACEHOLDER_KEY = re.compile(r"^[a-zA-Z0-9_.]+$")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")


def validate_config_path_template(value: str | None) -> str | None:
    """The stripped template, ``None`` for empty input; ``ValueError`` for an unusable one."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > MAX_TEMPLATE_CHARS:
        raise ValueError(f"config path template must be at most {MAX_TEMPLATE_CHARS} characters")
    if "\\" in text or "\x00" in text:
        raise ValueError("config path template must use '/' and no control characters")
    if text.startswith("/") or _WINDOWS_DRIVE.match(text):
        raise ValueError("config path template must be relative to the repository root")
    # Colons are only legal inside placeholders' text: none of the keys contain one.
    if ":" in _PLACEHOLDER.sub("", text):
        raise ValueError("config path template must not contain ':'")
    if any(part == ".." for part in text.split("/")):
        raise ValueError("config path template must not contain '..' segments")

    keys: list[str] = []
    for match in _PLACEHOLDER.finditer(text):
        key = match.group(1)
        if not _PLACEHOLDER_KEY.match(key):
            raise ValueError("config path template has a malformed placeholder")
        if key.split(".", 1)[0] not in ALLOWED_NAMESPACES or "." not in key:
            raise ValueError(
                "config path template placeholders must start with one of "
                f"{', '.join(sorted(ALLOWED_NAMESPACES))} (for example {{device.name}})"
            )
        keys.append(key)
    if "{" in _PLACEHOLDER.sub("", text) or "}" in _PLACEHOLDER.sub("", text):
        raise ValueError("config path template has an unbalanced brace")
    if not any(k.startswith(_PER_DEVICE_PREFIXES) for k in keys):
        raise ValueError(
            "config path template must contain a {device.*} or {nautobot.*} placeholder, "
            "otherwise every device would read the same file"
        )
    return text
