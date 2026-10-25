"""Get the repository up to date with the ``git`` CLI and list the files to read.

Run once at startup. Credentials never appear in an argument list (visible in ``ps``) or in a
log line: a token travels in the environment of the child process only, is offered to the
configured origin only, and every message that leaves this module is scrubbed.
"""

from __future__ import annotations

import base64
import logging
import re
import shlex
import subprocess  # noqa: S404 - the git CLI is the whole point of this module
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import urlsplit

from manus_agent.data_config import DataConfig, GitSettings

logger = logging.getLogger("manus_agent.git_source")

GIT_TIMEOUT_SECONDS = 300
MAX_FILES = 5000
_URL_CREDENTIALS = re.compile(r"(?P<scheme>[a-z+]+://)[^/@\s]+@")

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class GitSourceError(RuntimeError):
    """The repository could not be updated or read (the text is already scrubbed)."""


def scrub(text: str, secrets: tuple[str, ...] = ()) -> str:
    """Remove URL credentials and the given secret values from *text*."""
    cleaned = _URL_CREDENTIALS.sub(r"\g<scheme>***@", text)
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "***")
    return cleaned


def _origin(url: str) -> str:
    """``https://host[:port]/`` of an https URL (the scope of the credential header)."""
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/"


def _git_env(git: GitSettings, env: Mapping[str, str]) -> tuple[dict[str, str], tuple[str, ...]]:
    """The environment for git and the secret values to scrub from its output."""
    child = {
        key: env[key]
        for key in ("PATH", "HOME", "LANG", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE")
        if key in env
    }
    child["GIT_TERMINAL_PROMPT"] = "0"
    # A remote must not be able to send the client to a host the configuration never named.
    config: list[tuple[str, str]] = [("http.followRedirects", "false")]
    secrets: tuple[str, ...] = ()
    if not git.verify_ssl:
        logger.warning("TLS certificate verification is turned off (git.verify_ssl: false)")
        config.append(("http.sslVerify", "false"))
    if git.auth.type == "token":
        token = env.get(git.auth.token_env or "", "")
        basic = base64.b64encode(f"{git.auth.username}:{token}".encode()).decode()
        # http.<origin>.extraHeader: git sends it to that origin only, not to any other host.
        config.append((f"http.{_origin(git.url)}.extraHeader", f"Authorization: Basic {basic}"))
        secrets = (token, basic)
    elif git.auth.type == "ssh" and git.auth.key_file is not None:
        # git runs this string through a shell: quote every path (data_config also restricts them).
        child["GIT_SSH_COMMAND"] = (
            f"ssh -i {shlex.quote(str(git.auth.key_file))} -o IdentitiesOnly=yes "
            "-o BatchMode=yes -o StrictHostKeyChecking=accept-new "
            f"-o UserKnownHostsFile={shlex.quote(str(git.state_dir / 'known_hosts'))}"
        )
    # GIT_CONFIG_* (git >= 2.31) instead of ``-c``: the header would show up in the process list.
    child["GIT_CONFIG_COUNT"] = str(len(config))
    for index, (key, value) in enumerate(config):
        child[f"GIT_CONFIG_KEY_{index}"] = key
        child[f"GIT_CONFIG_VALUE_{index}"] = value
    return child, secrets


def sync_repository(
    git: GitSettings, env: Mapping[str, str], *, runner: Runner = subprocess.run
) -> Path:
    """Clone the repository, or fetch and hard-reset an existing checkout to the branch tip."""
    child_env, secrets = _git_env(git, env)
    checkout = git.checkout_dir
    git.state_dir.mkdir(parents=True, exist_ok=True)

    def run(*args: str) -> None:
        try:
            runner(
                ["git", *args],
                env=child_env,
                check=True,
                capture_output=True,
                text=True,
                timeout=GIT_TIMEOUT_SECONDS,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.CalledProcessError as exc:
            lines = (exc.stderr or "").strip().splitlines()
            detail = scrub(lines[-1] if lines else "", secrets)
            raise GitSourceError(f"git {args[0]} failed ({detail or 'no message'})") from None
        except subprocess.TimeoutExpired:
            raise GitSourceError(f"git {args[0]} timed out after {GIT_TIMEOUT_SECONDS}s") from None
        except FileNotFoundError:
            raise GitSourceError("the git executable was not found") from None

    if (checkout / ".git").is_dir():
        logger.info("updating the checkout of branch %s", git.branch)
        run("-C", str(checkout), "remote", "set-url", "origin", git.url)
        run("-C", str(checkout), "fetch", "--depth", "1", "origin", git.branch)
        run("-C", str(checkout), "reset", "--hard", "FETCH_HEAD")
        run("-C", str(checkout), "clean", "-fdx")
    else:
        logger.info("cloning branch %s", git.branch)
        checkout.parent.mkdir(parents=True, exist_ok=True)
        run(
            "clone",
            "--depth",
            "1",
            "--branch",
            git.branch,
            "--single-branch",
            "--",
            git.url,
            str(checkout),
        )
    return checkout


def list_source_files(checkout: Path, directory: str, pattern: str) -> list[Path]:
    """Regular files matching *pattern* in *directory*, sorted; nothing may leave the checkout."""
    root = checkout.resolve()
    base = (root / directory).resolve() if directory else root
    if not base.is_relative_to(root):
        raise GitSourceError("source.directory is outside the repository")
    if not base.is_dir():
        raise GitSourceError("source.directory does not exist in the repository")
    files: list[Path] = []
    for path in sorted(base.glob(pattern)):
        resolved = path.resolve()
        if not resolved.is_file() or not resolved.is_relative_to(root):
            continue
        if ".git" in resolved.relative_to(root).parts:
            continue
        files.append(resolved)
    if len(files) > MAX_FILES:
        raise GitSourceError(f"more than {MAX_FILES} files match the pattern")
    return files


def fetch_files(config: DataConfig, env: Mapping[str, str]) -> list[Path]:
    checkout = sync_repository(config.git, env)
    return list_source_files(checkout, config.source.directory, config.source.filename_pattern)
