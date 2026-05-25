"""
Git Environment Management Service.

This module handles environment variable management for git operations,
particularly SSL-related settings and environment cleanup.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Dict


@contextmanager
def set_ssl_env(repository: Dict):
    """Context manager to apply SSL-related environment variables for Git commands.

    Honors the 'verify_ssl' flag in the repository dict. Optionally supports
    custom CA/cert paths if keys are present (ssl_ca_info, ssl_cert).

    Args:
        repository: Repository metadata dict with SSL configuration

    Yields:
        None (context manager for environment variable management)

    Example:
        >>> repo = {"verify_ssl": False}
        >>> with set_ssl_env(repo):
        ...     # Git operations here will not verify SSL
        ...     pass
    """
    original = {
        "GIT_SSL_NO_VERIFY": os.environ.get("GIT_SSL_NO_VERIFY"),
        "GIT_SSL_CA_INFO": os.environ.get("GIT_SSL_CA_INFO"),
        "GIT_SSL_CERT": os.environ.get("GIT_SSL_CERT"),
    }
    try:
        if not repository.get("verify_ssl", True):
            os.environ["GIT_SSL_NO_VERIFY"] = "1"
        if repository.get("ssl_ca_info"):
            os.environ["GIT_SSL_CA_INFO"] = str(repository["ssl_ca_info"])
        if repository.get("ssl_cert"):
            os.environ["GIT_SSL_CERT"] = str(repository["ssl_cert"])
        yield
    finally:
        # Restore prior values (unset if previously absent)
        for key, val in original.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val
