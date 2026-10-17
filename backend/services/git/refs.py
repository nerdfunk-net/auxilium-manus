"""Git ref-name validation (pure, no imports from other services)."""

from __future__ import annotations

import re

_BRANCH_ALLOWED = re.compile(r"^[A-Za-z0-9._/+@-]{1,255}$")


def validate_branch_name(value: str) -> str:
    """Allow-list: ``[A-Za-z0-9._/+@-]``, no leading ``-`` or ``/``, no ``..``, no ``@{``,
    no ``//``, no trailing ``/``, ``.`` or ``.lock``.

    Keeps an attacker-chosen branch from being parsed as a git option (for example
    ``--output=<file>``, which makes ``git log`` overwrite a file).
    """
    name = (value or "").strip()
    if not _BRANCH_ALLOWED.fullmatch(name):
        raise ValueError("branch contains characters that are not allowed in a branch name")
    if name.startswith(("-", "/")) or name.endswith(("/", ".", ".lock")):
        raise ValueError("branch must not start with '-' or '/' or end with '/', '.' or '.lock'")
    if ".." in name or "@{" in name or "//" in name:
        raise ValueError("branch must not contain '..', '@{' or '//'")
    return name
