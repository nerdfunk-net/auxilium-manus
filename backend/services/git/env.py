"""Per-call Git environment overrides.

These helpers build the environment for a single git operation and return it to
the caller. Nothing here writes to ``os.environ`` — that is the whole point (see
FABLE_BACKEND S7): the web process and the Hatchet workers run git operations
concurrently, and a process-global ``GIT_SSL_NO_VERIFY`` / ``GIT_SSH_COMMAND``
set for one repository would leak into every other in-flight git subprocess.

Callers pass the result of :func:`build_git_env_overrides` to
``Repo.clone_from(..., env=...)``, ``repo.git.custom_environment(**...)``, or —
for a raw ``subprocess.run`` — to :func:`merge_git_environ` first.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

from services.git.ssh_command import build_git_ssh_command

logger = logging.getLogger(__name__)

_GIT_ENV_KEYS = ("GIT_SSL_NO_VERIFY", "GIT_SSL_CA_INFO", "GIT_SSL_CERT", "GIT_SSH_COMMAND")


def build_git_env_overrides(
    repository: dict,
    *,
    ssh_key_path: str | None = None,
) -> dict[str, str]:
    """Return the ``GIT_*`` environment overrides for one git operation.

    Honours ``verify_ssl`` (default ``True``) and the optional ``ssl_ca_info`` /
    ``ssl_cert`` keys on the repository dict. When ``ssh_key_path`` is given, a
    per-call ``GIT_SSH_COMMAND`` is included. Does not touch ``os.environ``.
    """
    overrides: dict[str, str] = {}

    if not repository.get("verify_ssl", True):
        host = "unknown"
        try:
            host = urlparse(repository.get("url") or "").hostname or "unknown"
        except ValueError:
            pass
        logger.warning("Git SSL verification disabled for repository url_host=%s", host)
        overrides["GIT_SSL_NO_VERIFY"] = "1"

    if repository.get("ssl_ca_info"):
        overrides["GIT_SSL_CA_INFO"] = str(repository["ssl_ca_info"])
    if repository.get("ssl_cert"):
        overrides["GIT_SSL_CERT"] = str(repository["ssl_cert"])

    if ssh_key_path:
        overrides["GIT_SSH_COMMAND"] = build_git_ssh_command(ssh_key_path)

    return overrides


def merge_git_environ(overrides: dict[str, str]) -> dict[str, str]:
    """Return a full environment mapping for ``subprocess.run(..., env=...)``.

    Starts from a copy of ``os.environ`` with every inherited ``GIT_*`` override
    cleared first, so a polluted parent environment cannot keep
    ``GIT_SSL_NO_VERIFY`` set for a ``verify_ssl=True`` repository, then applies
    ``overrides``. Does not mutate ``os.environ``.
    """
    env = os.environ.copy()
    for key in _GIT_ENV_KEYS:
        env.pop(key, None)
    env.update(overrides)
    return env
