"""Typed result objects and errors for :mod:`services.credentials.manager`.

The ``CredentialManager`` facade returns these small frozen dataclasses instead
of the bare tuples the three legacy resolver seams used, so callers stop
positionally unpacking secrets.
"""

from __future__ import annotations

from dataclasses import dataclass


class CredentialLookupError(ValueError):
    """No credential matched the requested name/id in the visible scope."""


class CredentialUnusableError(ValueError):
    """A credential was found but cannot serve the requested purpose.

    Wrong type, expired, or it has no decryptable secret.
    """


@dataclass(frozen=True)
class SshSecret:
    """An ``ssh`` credential resolved to a username/password pair."""

    username: str
    password: str


@dataclass(frozen=True)
class GenericSecret:
    """An ``ssh`` or ``generic`` credential resolved for a non-SSH transport."""

    username: str
    password: str


@dataclass(frozen=True)
class SharedSecret:
    """A ``shared_secret`` credential resolved to ``(algorithm, passphrase)``."""

    algorithm: str
    passphrase: str


@dataclass(frozen=True)
class SourceSecret:
    """A global credential resolved for a background source integration."""

    username: str | None
    password: str


@dataclass(frozen=True)
class GitSecret:
    """Git auth material resolved from a repository dict.

    ``ssh_key_path`` is set for ``ssh_key`` auth (the key is materialised on
    disk); ``token`` is set for ``token``/``generic`` auth.
    """

    username: str | None
    token: str | None
    ssh_key_path: str | None
