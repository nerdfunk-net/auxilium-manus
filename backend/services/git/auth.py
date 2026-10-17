"""Git Authentication Service.

This service centralizes all Git authentication logic, including:
- Credential resolution from credential_name
- SSH key path retrieval
- Token/password decryption
- Authentication header value (no credentials in URLs)
- SSH command environment setup
- URL normalization for comparison

This replaces scattered authentication code across git routers and eliminates
duplication of auth setup logic.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from urllib.parse import urlparse, urlunparse

from services.credentials.credentials_service import discard_ephemeral_ssh_key
from services.credentials.exceptions import (
    CredentialVaultNotConfiguredError,
    CredentialVaultUnavailableError,
)
from services.git.auth_header import auth_header_value  # noqa: F401  (re-export)

logger = logging.getLogger(__name__)


def strip_http_userinfo(url: str) -> str:
    """Remove ``user:pass@`` from an http(s) URL; every other URL is returned untouched."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or "@" not in parsed.netloc:
            return url
        return urlunparse(parsed._replace(netloc=parsed.netloc.rsplit("@", 1)[-1]))
    except ValueError:
        return url


class GitAuthenticationService:
    """Service for handling Git authentication operations."""

    def resolve_credentials(self, repository: dict) -> tuple[str | None, str | None, str | None]:
        """Resolve username, token/password, and SSH key path from credential_name.

        Git sync/clone/debug flows have no acting-user context anywhere in this
        call chain (background jobs, not an authenticated HTTP request), so
        resolution is scoped to global credentials only — a private credential
        matching ``credential_name`` is treated as not found. Known limitation:
        git repositories cannot use private credentials, only global ones.

        Args:
            repository: Repository metadata dict with credential_name and auth_type

        Returns:
            Tuple of (username, token, ssh_key_path) - ssh_key_path is set for ssh_key auth
        """
        credential_name = repository.get("credential_name")
        if not credential_name:
            logger.debug("No credential_name provided, returning None")
            return None, None, None

        try:
            from core.database import SessionLocal
            from services.credentials.manager import CredentialManager

            db = SessionLocal()
            try:
                secret = CredentialManager(db).git(repository)
                return secret.username, secret.token, secret.ssh_key_path
            finally:
                db.close()
        except (CredentialVaultUnavailableError, CredentialVaultNotConfiguredError):
            # A vault-backed credential could not be reached — fail loudly rather
            # than silently degrade to "no auth".
            raise
        except Exception as e:
            logger.error(
                "Failed to resolve credentials for '%s': %s",
                credential_name,
                e,
                exc_info=True,
            )
            return None, None, None

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

    @contextmanager
    def setup_auth_environment(self, repository: dict):
        """Context manager that resolves Git credentials for one operation.

        It resolves ``credential_name`` (falling back to an inline token) and,
        for token auth over http(s), yields the URL **without** credentials (S3-01).
        It does **not** touch ``os.environ``: SSH-key setup is done per-call by
        the caller via ``services.git.env.build_git_env_overrides`` (which builds
        ``GIT_SSH_COMMAND``) and passed to GitPython/subprocess as ``env=``.

        Args:
            repository: Repository metadata dict with auth_type, credential_name, url, etc.

        Yields:
            Tuple of (clone_url, username, token, ssh_key_path)
            - clone_url: the repository URL, never carrying the token
            - username: Resolved username
            - token: Resolved token/password
            - ssh_key_path: Path to SSH key file (for SSH auth), for the caller to
              hand to ``build_git_env_overrides``. Removed again when the context
              exits if it is an ephemeral vault-backed file (V2).

        Example:
            with auth_service.setup_auth_environment(repo) as (url, user, token, ssh_key):
                overrides = build_git_env_overrides(
                    repo, ssh_key_path=ssh_key, username=user, token=token
                )
                Repo.clone_from(url, path, env=overrides)
        """
        username, token, ssh_key_path = self.resolve_credentials(repository)
        try:
            if not token:
                inline_token = repository.get("token")
                if inline_token:
                    token = str(inline_token)
                    username = username or repository.get("username")
            auth_type = repository.get("auth_type", "token")
            original_url = repository.get("url", "")

            if auth_type == "ssh_key" and ssh_key_path:
                logger.info(
                    "Using SSH key authentication for repository '%s'",
                    repository.get("name"),
                )
                # For SSH, return original URL; GIT_SSH_COMMAND is built per-call by the caller.
                yield original_url, username, token, ssh_key_path
            else:
                # For token auth the URL stays clean; the token travels in a per-process
                # ``http.<origin>/.extraHeader`` (services.git.env), never in argv or .git/config.
                clone_url = original_url
                parsed = urlparse(original_url) if original_url else None
                if parsed and parsed.scheme in ["http", "https"] and token:
                    clone_url = strip_http_userinfo(original_url)
                    logger.info(
                        "Using token authentication for repository '%s'",
                        repository.get("name"),
                    )
                else:
                    logger.info(
                        "Using no authentication for repository '%s'",
                        repository.get("name"),
                    )
                yield clone_url, username, token, ssh_key_path
        finally:
            # A vault-backed key is an ephemeral file (V2); a local export is left alone.
            discard_ephemeral_ssh_key(ssh_key_path)
