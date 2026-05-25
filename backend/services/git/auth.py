"""Git Authentication Service.

This service centralizes all Git authentication logic, including:
- Credential resolution from credential_name
- SSH key path retrieval
- Token/password decryption
- Authentication URL building
- SSH command environment setup
- URL normalization for comparison

This replaces scattered authentication code across git routers and eliminates
duplication of auth setup logic.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Dict, Optional, Tuple
from urllib.parse import quote as urlquote
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)


class GitAuthenticationService:
    """Service for handling Git authentication operations."""

    def resolve_credentials(
        self, repository: Dict
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Resolve username, token/password, and SSH key path from credential_name.

        Args:
            repository: Repository metadata dict with credential_name and auth_type

        Returns:
            Tuple of (username, token, ssh_key_path) - ssh_key_path is set for ssh_key auth
        """
        auth_type = repository.get("auth_type", "token")
        credential_name = repository.get("credential_name")

        logger.debug(
            "Resolving credentials: credential_name='%s', auth_type='%s'",
            credential_name,
            auth_type,
        )

        if not credential_name:
            logger.debug("No credential_name provided, returning None")
            return None, None, None

        try:
            import service_factory

            cred_mgr = service_factory.build_credentials_service()

            creds = cred_mgr.list_credentials(include_expired=False)
            logger.debug(
                "Found %s active credentials, searching for '%s' with type '%s'",
                len(creds),
                credential_name,
                auth_type,
            )

            if auth_type == "ssh_key":
                # Look for SSH key credential
                match = next(
                    (
                        c
                        for c in creds
                        if c["name"] == credential_name and c["type"] == "ssh_key"
                    ),
                    None,
                )
                if match:
                    logger.debug(
                        "Found SSH key credential: id=%s, username=%s",
                        match["id"],
                        match.get("username"),
                    )
                    # Get the SSH key file path
                    ssh_key_path = cred_mgr.get_ssh_key_path(match["id"])
                    if ssh_key_path:
                        logger.debug("SSH key path resolved: %s", ssh_key_path)
                        return match.get("username"), None, ssh_key_path
                    else:
                        logger.error(
                            "SSH key file not found for credential '%s'",
                            credential_name,
                        )
                        return None, None, None
                else:
                    logger.warning(
                        "SSH key credential '%s' not found in %s credentials",
                        credential_name,
                        len(creds),
                    )
                    return None, None, None
            elif auth_type == "generic":
                # Look for generic credential (username/password, not for SSH)
                match = next(
                    (
                        c
                        for c in creds
                        if c["name"] == credential_name and c["type"] == "generic"
                    ),
                    None,
                )
                if match:
                    username = match.get("username")
                    logger.debug(
                        "Found generic credential: id=%s, username=%s",
                        match["id"],
                        username,
                    )
                    try:
                        password = cred_mgr.get_decrypted_password(match["id"])
                        logger.debug(
                            "Successfully decrypted password for '%s'", credential_name
                        )
                        return username, password, None
                    except Exception as de:
                        logger.error(
                            "Failed to decrypt credential '%s': %s",
                            credential_name,
                            de,
                            exc_info=True,
                        )
                        return None, None, None
                else:
                    logger.warning(
                        "Generic credential '%s' not found in %s credentials",
                        credential_name,
                        len(creds),
                    )
                    logger.debug(
                        "Available generic credentials: %s",
                        [c["name"] for c in creds if c["type"] == "generic"],
                    )
                    return None, None, None
            else:
                # Look for token credential (default behavior)
                match = next(
                    (
                        c
                        for c in creds
                        if c["name"] == credential_name and c["type"] == "token"
                    ),
                    None,
                )
                if match:
                    username = match.get("username")
                    logger.debug(
                        "Found token credential: id=%s, username=%s",
                        match["id"],
                        username,
                    )
                    try:
                        token = cred_mgr.get_decrypted_password(match["id"])
                        logger.debug(
                            "Successfully decrypted token for '%s'", credential_name
                        )
                        return username, token, None
                    except Exception as de:
                        logger.error(
                            "Failed to decrypt credential '%s': %s",
                            credential_name,
                            de,
                            exc_info=True,
                        )
                        return None, None, None
                else:
                    logger.warning(
                        "Token credential '%s' not found in %s credentials",
                        credential_name,
                        len(creds),
                    )
                    logger.debug(
                        "Available token credentials: %s",
                        [c["name"] for c in creds if c["type"] == "token"],
                    )
                    return None, None, None
        except Exception as ce:
            logger.error("Error resolving credential '%s': %s", credential_name, ce)
            return None, None, None

    def build_auth_url(
        self, url: str, username: Optional[str], token: Optional[str]
    ) -> str:
        """Return a URL with HTTP(S) basic auth credentials injected.

        - Only applies to http/https URLs; other schemes (ssh/git) are returned untouched.
        - Username/token are URL-encoded.
        - If credentials are missing, the original URL is returned.

        Args:
            url: The Git repository URL
            username: Username for authentication (optional)
            token: Token or password for authentication (optional)

        Returns:
            URL with credentials embedded if applicable
        """
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return url
            if not token:
                return url
            user_enc = urlquote(str(username or "git"), safe="")
            token_enc = urlquote(str(token), safe="")
            netloc = parsed.netloc
            # Strip existing userinfo, then add ours
            if "@" in netloc:
                netloc = netloc.split("@", 1)[-1]
            netloc = f"{user_enc}:{token_enc}@{netloc}"
            return urlunparse(
                (
                    parsed.scheme,
                    netloc,
                    parsed.path,
                    parsed.params,
                    parsed.query,
                    parsed.fragment,
                )
            )
        except Exception:
            # Be conservative; return original URL on parsing errors
            return url

    def normalize_url(self, url: str) -> str:
        """Normalize a Git URL by removing any userinfo to enable safe comparison.

        Args:
            url: The Git repository URL

        Returns:
            Normalized URL without credentials
        """
        try:
            parsed = urlparse(url)
            netloc = parsed.netloc
            if "@" in netloc:
                netloc = netloc.split("@", 1)[-1]
            return urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))
        except Exception:
            return url

    def is_ssh_auth(self, repository: Dict) -> bool:
        """Check if repository uses SSH key authentication.

        Args:
            repository: Repository metadata dict

        Returns:
            True if auth_type is ssh_key
        """
        return repository.get("auth_type", "token") == "ssh_key"

    def is_token_auth(self, repository: Dict) -> bool:
        """Check if repository uses token authentication.

        Args:
            repository: Repository metadata dict

        Returns:
            True if auth_type is token (or default)
        """
        return repository.get("auth_type", "token") == "token"

    @contextmanager
    def setup_auth_environment(self, repository: Dict):
        """Context manager to setup authentication environment for Git operations.

        Handles:
        - SSH command setup for SSH key authentication
        - Credential resolution
        - Environment variable management
        - Automatic cleanup on exit

        Args:
            repository: Repository metadata dict with auth_type, credential_name, url, etc.

        Yields:
            Tuple of (clone_url, username, token, ssh_key_path)
            - clone_url: URL with auth injected (for token auth) or original (for SSH)
            - username: Resolved username
            - token: Resolved token/password
            - ssh_key_path: Path to SSH key file (for SSH auth)

        Example:
            with auth_service.setup_auth_environment(repo) as (url, user, token, ssh_key):
                if ssh_key:
                    # SSH auth is configured via GIT_SSH_COMMAND env var
                    Repo.clone_from(url, path)
                else:
                    # Token auth - url has credentials embedded
                    Repo.clone_from(url, path)
        """
        # Resolve credentials
        username, token, ssh_key_path = self.resolve_credentials(repository)
        auth_type = repository.get("auth_type", "token")
        original_url = repository.get("url", "")

        # Save original environment
        original_ssh_command = os.environ.get("GIT_SSH_COMMAND")

        try:
            if auth_type == "ssh_key" and ssh_key_path:
                # Set up SSH command for SSH key auth
                os.environ["GIT_SSH_COMMAND"] = (
                    f"ssh -i {ssh_key_path} -o StrictHostKeyChecking=no -o IdentitiesOnly=yes"
                )
                logger.info(
                    "Using SSH key authentication for repository '%s'",
                    repository.get("name"),
                )
                # For SSH, return original URL
                yield original_url, username, token, ssh_key_path
            else:
                # For token auth, build authenticated URL
                clone_url = original_url
                parsed = urlparse(original_url) if original_url else None
                if parsed and parsed.scheme in ["http", "https"] and token:
                    clone_url = self.build_auth_url(original_url, username, token)
                    logger.info(
                        "Using token authentication for repository '%s'",
                        repository.get("name"),
                    )
                else:
                    logger.info(
                        "Using no authentication for repository '%s'",
                        repository.get("name"),
                    )
                # For token auth, return authenticated URL
                yield clone_url, username, token, ssh_key_path
        finally:
            # Restore original SSH command environment
            if original_ssh_command is not None:
                os.environ["GIT_SSH_COMMAND"] = original_ssh_command
            elif "GIT_SSH_COMMAND" in os.environ:
                del os.environ["GIT_SSH_COMMAND"]
