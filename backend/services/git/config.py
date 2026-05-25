"""
Git Configuration Service.

This module handles git configuration for commits, particularly
user.name and user.email settings required for git operations.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Dict

from git import Repo

logger = logging.getLogger(__name__)


@contextmanager
def set_git_author(repository: Dict, repo: Repo):
    """Context manager to temporarily set git author configuration for commits.

    Sets user.name and user.email from repository configuration if provided.
    If not provided, uses default values to ensure commits can be made.
    Restores original configuration after the context exits.

    Args:
        repository: Repository metadata dict with git_author_name and git_author_email
        repo: GitPython Repo instance

    Yields:
        None (context manager for git config management)

    Example:
        >>> repo_dict = {"git_author_name": "John Doe", "git_author_email": "john@example.com"}
        >>> repo = Repo("/path/to/repo")
        >>> with set_git_author(repo_dict, repo):
        ...     # Git commits here will use the configured author
        ...     repo.index.commit("My commit message")
    """
    # Get current git config values
    config_reader = repo.config_reader()
    original_name = None
    original_email = None

    try:
        original_name = config_reader.get_value("user", "name", default=None)
    except Exception:
        pass

    try:
        original_email = config_reader.get_value("user", "email", default=None)
    except Exception:
        pass

    # Set new values from repository config or use defaults
    config_writer = repo.config_writer()
    try:
        author_name = repository.get("git_author_name") or "Cockpit-NG Automation"
        author_email = repository.get("git_author_email") or "noreply@cockpit-ng.local"

        config_writer.set_value("user", "name", author_name)
        config_writer.set_value("user", "email", author_email)
        config_writer.release()

        logger.debug("Set git author: %s <%s>", author_name, author_email)

        yield
    finally:
        # Restore original values
        config_writer = repo.config_writer()
        if original_name is not None:
            config_writer.set_value("user", "name", original_name)
        else:
            try:
                config_writer.remove_option("user", "name")
            except Exception:
                pass

        if original_email is not None:
            config_writer.set_value("user", "email", original_email)
        else:
            try:
                config_writer.remove_option("user", "email")
            except Exception:
                pass

        config_writer.release()
        logger.debug("Restored original git author configuration")
