"""
Git Connection Testing Service.

This service handles testing Git repository connections, including:
- Connection validation
- Authentication testing
- Shallow clone testing
- Credential resolution and validation
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

from models.git_repositories import GitConnectionTestRequest, GitConnectionTestResponse
from services.git.auth import GitAuthenticationService
from services.git.env import set_ssl_env

logger = logging.getLogger(__name__)


class GitConnectionService:
    """Service for testing Git repository connections."""

    def __init__(self):
        self._auth = GitAuthenticationService()

    def test_connection(
        self, test_request: GitConnectionTestRequest
    ) -> GitConnectionTestResponse:
        """Test git repository connection by attempting a shallow clone.

        Args:
            test_request: Connection test request with URL, branch, auth details

        Returns:
            GitConnectionTestResponse with success status and details

        Example:
            >>> request = GitConnectionTestRequest(
            ...     url="https://github.com/user/repo.git",
            ...     branch="main",
            ...     auth_type=GitAuthType.TOKEN,
            ...     credential_name="github-token"
            ... )
            >>> result = git_connection_service.test_connection(request)
            >>> result.success
            True
        """
        logger.info("=== Starting Git Connection Test ===")
        logger.info("URL: %s", test_request.url)
        logger.info("Branch: %s", test_request.branch)
        logger.info("Auth Type: %s", test_request.auth_type)
        logger.info("Credential Name: %s", test_request.credential_name)
        logger.info("Verify SSL: %s", test_request.verify_ssl)

        try:
            # Create temporary directory for test
            with tempfile.TemporaryDirectory() as temp_dir:
                test_path = Path(temp_dir) / "test_repo"

                # Get authentication type
                auth_type = (
                    test_request.auth_type.value if test_request.auth_type else "token"
                )
                logger.debug("Resolved auth_type to: %s", auth_type)

                # Create a temporary repository dict for credential resolution
                temp_repo = {
                    "credential_name": test_request.credential_name,
                    "auth_type": auth_type,
                    "username": test_request.username,  # fallback
                    "token": test_request.token,  # fallback
                    "url": test_request.url,
                    "verify_ssl": test_request.verify_ssl,
                }

                # Resolve credentials using authentication service
                logger.info("Resolving credentials for auth_type: %s", auth_type)
                resolved_username, resolved_token, ssh_key_path = (
                    self._auth.resolve_credentials(temp_repo)
                )

                # Log resolved credentials (without exposing secrets)
                logger.info("Credential resolution results:")
                logger.info(
                    "  - Username: %s",
                    resolved_username if resolved_username else "None",
                )
                logger.info(
                    "  - Token/Password: %s", "<present>" if resolved_token else "None"
                )
                logger.info(
                    "  - SSH Key Path: %s", ssh_key_path if ssh_key_path else "None"
                )

                # Validate credential resolution
                validation_result = self._validate_credentials(
                    test_request=test_request,
                    auth_type=auth_type,
                    resolved_username=resolved_username,
                    resolved_token=resolved_token,
                    ssh_key_path=ssh_key_path,
                )
                if validation_result:
                    return validation_result

                # Build authenticated clone URL
                clone_url = self._build_clone_url(
                    test_request=test_request,
                    auth_type=auth_type,
                    resolved_username=resolved_username,
                    resolved_token=resolved_token,
                )

                # Test clone with SSL environment
                with set_ssl_env(temp_repo):
                    return self._test_clone(
                        clone_url=clone_url,
                        branch=test_request.branch,
                        test_path=test_path,
                        auth_type=auth_type,
                        ssh_key_path=ssh_key_path,
                        test_request=test_request,
                    )

        except subprocess.TimeoutExpired:
            logger.warning("Git connection test timed out")
            return GitConnectionTestResponse(
                success=False,
                message="Git connection test timed out",
                details={"error": "Connection timeout after 30 seconds"},
            )
        except Exception as e:
            logger.error("Error testing git connection: %s", e)
            return GitConnectionTestResponse(
                success=False,
                message=f"Git connection test error: {str(e)}",
                details={"error": str(e)},
            )

    def _validate_credentials(
        self,
        test_request: GitConnectionTestRequest,
        auth_type: str,
        resolved_username: str,
        resolved_token: str,
        ssh_key_path: str,
    ) -> GitConnectionTestResponse | None:
        """Validate that credentials were properly resolved.

        Args:
            test_request: Original test request
            auth_type: Authentication type (token, ssh_key, none)
            resolved_username: Resolved username from credentials
            resolved_token: Resolved token from credentials
            ssh_key_path: Resolved SSH key path from credentials

        Returns:
            GitConnectionTestResponse if validation failed, None if successful
        """
        # Validate SSH key credentials
        if auth_type == "ssh_key":
            if test_request.credential_name and not ssh_key_path:
                return GitConnectionTestResponse(
                    success=False,
                    message=f"Failed to resolve SSH key credential '{test_request.credential_name}' - credential not found or SSH key file missing",
                    details={},
                )

        # Validate token credentials
        elif auth_type == "token":
            if test_request.credential_name and not resolved_token:
                return GitConnectionTestResponse(
                    success=False,
                    message=f"Failed to resolve credential '{test_request.credential_name}' - credential not found, not a token type, or decryption failed",
                    details={},
                )

        # Validate generic credentials
        elif auth_type == "generic":
            if test_request.credential_name and not resolved_token:
                return GitConnectionTestResponse(
                    success=False,
                    message=f"Failed to resolve generic credential '{test_request.credential_name}' - credential not found, not a generic type, or decryption failed",
                    details={},
                )

        return None

    def _build_clone_url(
        self,
        test_request: GitConnectionTestRequest,
        auth_type: str,
        resolved_username: str,
        resolved_token: str,
    ) -> str:
        """Build the clone URL with authentication if needed.

        Args:
            test_request: Original test request
            auth_type: Authentication type
            resolved_username: Resolved username
            resolved_token: Resolved token

        Returns:
            Clone URL with authentication embedded if using token auth
        """
        clone_url = test_request.url
        logger.info("Building clone URL for auth_type: %s", auth_type)

        # Both 'token' and 'generic' auth types use username/password in URL
        if auth_type in ["token", "generic"] and resolved_username and resolved_token:
            logger.info("Adding %s authentication to URL", auth_type)
            # Add authentication to URL using the service
            clone_url = self._auth.build_auth_url(
                clone_url, resolved_username, resolved_token
            )
            logger.debug("Authentication added to URL (credentials hidden)")
        else:
            logger.info(
                "No authentication added to URL (auth_type=%s, has_username=%s, has_token=%s)",
                auth_type,
                bool(resolved_username),
                bool(resolved_token),
            )

        return clone_url

    def _test_clone(
        self,
        clone_url: str,
        branch: str,
        test_path: Path,
        auth_type: str,
        ssh_key_path: str,
        test_request: GitConnectionTestRequest,
    ) -> GitConnectionTestResponse:
        """Perform the actual shallow clone test.

        Args:
            clone_url: URL to clone (with auth if token-based)
            branch: Branch to clone
            test_path: Local path for test clone
            auth_type: Authentication type
            ssh_key_path: SSH key path if using SSH auth
            test_request: Original test request

        Returns:
            GitConnectionTestResponse with test results
        """
        # Set up environment
        env = os.environ.copy()

        # Handle SSH key authentication
        if auth_type == "ssh_key" and ssh_key_path:
            env["GIT_SSH_COMMAND"] = (
                f'ssh -i "{ssh_key_path}" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
            )

        # Build shallow clone command
        cmd = [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            branch,
            clone_url,
            str(test_path),
        ]

        logger.info("Executing git clone command...")
        logger.debug(
            "Command: git clone --depth 1 --branch %s <url> %s", branch, test_path
        )
        logger.debug(
            "Environment SSH_COMMAND: %s", env.get("GIT_SSH_COMMAND", "not set")
        )

        # Execute clone with timeout
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,  # 30 second timeout
        )

        # Parse result
        if result.returncode == 0:
            logger.info(
                "Git connection test successful for %s (branch: %s)",
                test_request.url,
                branch,
            )
            return GitConnectionTestResponse(
                success=True,
                message="Git connection successful",
                details={
                    "branch": branch,
                    "url": test_request.url,
                    "auth_type": auth_type,
                },
            )
        else:
            logger.warning(
                "Git connection test failed for %s: %s", test_request.url, result.stderr
            )
            return GitConnectionTestResponse(
                success=False,
                message=f"Git connection failed: {result.stderr}",
                details={"error": result.stderr, "return_code": result.returncode},
            )
