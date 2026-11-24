"""One closed list of device CLI error markers (C2-01).

The labels are a closed vocabulary: device text is never copied out of this module, because a
refused line may echo a rendered secret (``tacacs-server key ...``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_CLI_ERRORS: tuple[tuple[str, str], ...] = (
    ("invalid_input", r"^\s*%\s*Invalid input detected"),
    ("invalid_input", r"^\s*%\s*Invalid (?:input|command)\b"),  # EOS, NX-OS, Comware
    ("incomplete_command", r"^\s*%\s*Incomplete command"),
    ("ambiguous_command", r"^\s*%\s*Ambiguous command"),
    ("unknown_command", r"^\s*%\s*(?:Unknown|Unrecognized) command"),
    ("unknown_command", r"^\s*unknown command\b"),  # Junos
    ("syntax_error", r"^\s*Syntax error while parsing\b"),  # NX-OS
    ("syntax_error", r"^\s*(?:error: )?syntax error\b"),  # Junos
    ("authorization_failed", r"^\s*Command authorization failed\b"),  # TACACS+ / RADIUS
    ("authorization_failed", r"^\s*%\s*Authorization failed\b"),
    ("access_denied", r"^\s*%\s*Access denied\b"),
    ("bad_value", r"^\s*%\s*Bad (?:IP address|mask|hostname)\b"),
)
_COMPILED = tuple((label, re.compile(rx, re.I | re.M)) for label, rx in _CLI_ERRORS)

# Netmiko applies error_pattern with re.M only, hence the scoped (?i:...).
CONFIG_ERROR_PATTERN = "(?i:" + "|".join(rx for _, rx in _CLI_ERRORS) + ")"

# Commit failures on commit-model platforms (IOS-XR, Junos); see NetmikoDeviceSession.
_COMMIT_ERRORS: tuple[tuple[str, str], ...] = (
    ("commit_failed", r"failed to commit"),
    ("commit_failed", r"commit failed"),
    ("commit_failed", r"^\s*error: (?:configuration check-out failed|commit failed)"),
)
_COMMIT_COMPILED = tuple((label, re.compile(rx, re.I | re.M)) for label, rx in _COMMIT_ERRORS)


# ``copy <file> running-config`` keeps loading after these lines and still returns to the prompt,
# so Netmiko sees a clean success (merge-config, W3a-02). The unreadable source is never
# optional; a warning is a refusal like any other and follows ``fail_on_cli_error``.
_COPY_OPEN_ERRORS: tuple[tuple[str, str], ...] = (("copy_error_opening", r"^\s*%\s*Error opening"),)
_COPY_WARNINGS: tuple[tuple[str, str], ...] = (("copy_warning", r"^\s*%\s*Warning"),)
_COPY_OPEN_COMPILED = tuple((label, re.compile(rx, re.I | re.M)) for label, rx in _COPY_OPEN_ERRORS)
_COPY_WARNING_COMPILED = tuple((label, re.compile(rx, re.I | re.M)) for label, rx in _COPY_WARNINGS)


@dataclass(frozen=True)
class CliError:
    label: str  # closed vocabulary above
    line: int  # 1-based line of the offending output


def find_cli_error(output: str) -> CliError | None:
    for label, rx in _COMPILED:
        if (match := rx.search(output)) is not None:
            return CliError(label, output.count("\n", 0, match.start()) + 1)
    return None


def find_commit_error(output: str) -> CliError | None:
    for label, rx in _COMMIT_COMPILED:
        if (match := rx.search(output)) is not None:
            return CliError(label, output.count("\n", 0, match.start()) + 1)
    return None


def _first_match(output: str, compiled: tuple[tuple[str, re.Pattern[str]], ...]) -> CliError | None:
    for label, rx in compiled:
        if (match := rx.search(output)) is not None:
            return CliError(label, output.count("\n", 0, match.start()) + 1)
    return None


def find_copy_error(output: str, *, fail_on_cli_error: bool = True) -> CliError | None:
    """The first sign that ``copy <file> running-config`` did not apply (label and line only).

    An unreadable source file always counts; warnings and the shared CLI refusal markers only
    with ``fail_on_cli_error``.
    """
    if (opening := _first_match(output, _COPY_OPEN_COMPILED)) is not None:
        return opening
    if not fail_on_cli_error:
        return None
    return _first_match(output, _COPY_WARNING_COMPILED) or find_cli_error(output)
