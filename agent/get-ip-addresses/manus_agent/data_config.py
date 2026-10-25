"""The data source of this agent: ``config.yaml`` (git repository, files, column mapping).

Transport settings (agent id, secret, ports) stay in the environment (``config.py``). Secrets are
never read from this file: a token comes from the environment variable it names, an SSH key from
the file it names.

Everything the agent writes (the checkout, the SSH known_hosts file) lives under one state
directory, ``MANUS_AGENT_STATE_DIR`` (``/data`` in the image, ``/var/lib/manus-agent`` under
systemd); ``git.checkout_dir`` is a path inside it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from manus_agent.csv_reader import ALLOWED_DELIMITERS
from manus_agent.device_mapping import MappingRule, validate_mapping

DEFAULT_PATH = "config.yaml"
STATE_DIR_ENV = "MANUS_AGENT_STATE_DIR"
ALLOW_FILE_URLS_ENV = "MANUS_AGENT_ALLOW_FILE_URLS"
DEFAULT_STATE_DIR = "state"
MAX_CONFIG_BYTES = 256 * 1024

_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_URL = re.compile(r"^(https://|ssh://|file://|[\w.-]+@[\w.-]+:)[^\s]+$")
_KEY_FILE = re.compile(r"^[A-Za-z0-9_./@:+=,-]+$")
_SSH_PASSWORD = re.compile(r"^ssh://[^/@]*:[^/@]*@")
_AUTH_TYPES = ("none", "token", "ssh")


class DataConfigError(ValueError):
    """config.yaml does not describe a usable data source (never contains a secret)."""


@dataclass(frozen=True)
class GitAuth:
    type: str = "none"
    username: str = "oauth2"
    token_env: str | None = None
    key_file: Path | None = None


@dataclass(frozen=True)
class GitSettings:
    url: str = field(repr=False)
    branch: str
    auth: GitAuth
    verify_ssl: bool
    checkout_dir: Path
    state_dir: Path


@dataclass(frozen=True)
class SourceSettings:
    directory: str
    filename_pattern: str
    csv_delimiter: str


@dataclass(frozen=True)
class DataConfig:
    git: GitSettings
    source: SourceSettings
    mapping: tuple[MappingRule, ...]


def _section(raw: Mapping[str, Any], key: str, allowed: set[str], *, required: bool) -> dict:
    value = raw.get(key)
    if value is None:
        if required:
            raise DataConfigError(f"{key}: section is required")
        return {}
    if not isinstance(value, Mapping):
        raise DataConfigError(f"{key}: must be a mapping")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise DataConfigError(f"{key}: unknown key {unknown[0]!r}")
    return dict(value)


def _string(section: Mapping[str, Any], name: str, label: str, default: str | None = None) -> str:
    value = section.get(name, default)
    if not isinstance(value, str) or not value.strip():
        raise DataConfigError(f"{label}.{name}: a non-empty text is required")
    return value.strip()


def _relative(value: str, label: str) -> str:
    """A repository-relative path: no absolute path, no ``..`` (containment is checked again
    against the real checkout when the files are listed)."""
    normalized = value.replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if path.is_absolute() or re.match(r"^[A-Za-z]:", normalized) or ".." in path.parts:
        raise DataConfigError(f"{label}: must be a relative path inside the repository")
    return "" if normalized in ("", ".") else path.as_posix()


def _checkout_dir(git: Mapping[str, Any], state_dir: Path) -> Path:
    """The checkout, confined to the state directory (it is hard-reset and cleaned on start)."""
    relative = _string(git, "checkout_dir", "git", "repo")
    if Path(relative).is_absolute() or ".." in PurePosixPath(relative.replace("\\", "/")).parts:
        raise DataConfigError(
            f"git.checkout_dir: use a path relative to the state directory ({STATE_DIR_ENV})"
        )
    checkout = (state_dir / relative).resolve()
    if checkout == state_dir or not checkout.is_relative_to(state_dir):
        raise DataConfigError("git.checkout_dir: must be a directory inside the state directory")
    return checkout


def _auth(raw: Any, env: Mapping[str, str], url: str) -> GitAuth:
    if raw is None:
        return GitAuth()
    if not isinstance(raw, Mapping):
        raise DataConfigError("git.auth: must be a mapping")
    unknown = sorted(set(raw) - {"type", "username", "token_env", "key_file"})
    if unknown:
        raise DataConfigError(f"git.auth: unknown key {unknown[0]!r}")
    kind = raw.get("type", "none")
    if kind not in _AUTH_TYPES:
        raise DataConfigError(f"git.auth.type must be one of {', '.join(_AUTH_TYPES)}")
    if kind == "none":
        return GitAuth()
    if kind == "token":
        if not url.startswith("https://"):
            raise DataConfigError("git.auth: a token needs an https:// git.url")
        token_env = _string(raw, "token_env", "git.auth")
        if not _ENV_NAME.fullmatch(token_env):
            raise DataConfigError("git.auth.token_env: not a valid environment variable name")
        if not env.get(token_env):
            raise DataConfigError(f"git.auth: environment variable {token_env} is not set")
        username = _string(raw, "username", "git.auth", "oauth2")
        return GitAuth("token", username=username, token_env=token_env)
    key_text = _string(raw, "key_file", "git.auth")
    if not _KEY_FILE.fullmatch(key_text):
        # The path ends up in a shell command (GIT_SSH_COMMAND): plain path characters only.
        raise DataConfigError("git.auth.key_file: use only letters, digits and _ . / @ : + = , -")
    key_file = Path(key_text)
    if not key_file.is_absolute():
        raise DataConfigError("git.auth.key_file: use an absolute path")
    if not key_file.is_file():
        raise DataConfigError("git.auth.key_file: file not found")
    return GitAuth("ssh", key_file=key_file)


def parse_data_config(raw: Any, env: Mapping[str, str]) -> DataConfig:
    if not isinstance(raw, Mapping):
        raise DataConfigError("the file must contain a mapping with git, source and mapping")
    unknown = sorted(set(raw) - {"git", "source", "mapping"})
    if unknown:
        raise DataConfigError(f"unknown top-level key {unknown[0]!r}")

    git = _section(
        raw, "git", {"url", "branch", "auth", "verify_ssl", "checkout_dir"}, required=True
    )
    url = _string(git, "url", "git")
    if not _URL.fullmatch(url) or url.startswith("-"):
        raise DataConfigError("git.url: use an https://, ssh:// or user@host:path URL")
    if url.startswith("file://") and env.get(ALLOW_FILE_URLS_ENV) != "1":
        raise DataConfigError(
            f"git.url: file:// is for development only (set {ALLOW_FILE_URLS_ENV}=1)"
        )
    if (re.match(r"^https://[^/@]*@", url)) or _SSH_PASSWORD.match(url):
        raise DataConfigError("git.url: credentials do not belong in the URL, see git.auth")
    branch = _string(git, "branch", "git", "main")
    if not _BRANCH.fullmatch(branch) or ".." in branch or branch.endswith((".lock", "/")):
        raise DataConfigError("git.branch: not a valid branch name")
    verify_ssl = git.get("verify_ssl", True)
    if not isinstance(verify_ssl, bool):
        raise DataConfigError("git.verify_ssl: must be true or false")

    source = _section(
        raw, "source", {"directory", "filename_pattern", "csv_delimiter"}, required=False
    )
    pattern = _string(source, "filename_pattern", "source", "*.csv")
    if pattern.startswith(("/", "\\")) or ".." in pattern.replace("\\", "/").split("/"):
        raise DataConfigError("source.filename_pattern: must be a relative pattern")
    delimiter = source.get("csv_delimiter", ";")
    if delimiter == "\\t":
        delimiter = "\t"
    if delimiter not in ALLOWED_DELIMITERS:
        raise DataConfigError("source.csv_delimiter: must be one of ; , tab |")
    directory = source.get("directory", "")
    if not isinstance(directory, str):
        raise DataConfigError("source.directory: must be text")

    try:
        rules = validate_mapping(raw.get("mapping"))
    except ValueError as exc:
        raise DataConfigError(str(exc)) from exc

    state_dir = Path(env.get(STATE_DIR_ENV, "").strip() or DEFAULT_STATE_DIR).resolve()
    checkout = _checkout_dir(git, state_dir)
    return DataConfig(
        git=GitSettings(
            url=url,
            branch=branch,
            auth=_auth(git.get("auth"), env, url),
            verify_ssl=verify_ssl,
            checkout_dir=checkout,
            state_dir=state_dir,
        ),
        source=SourceSettings(_relative(directory, "source.directory"), pattern, delimiter),
        mapping=tuple(rules),
    )


def load_data_config(path: Path, env: Mapping[str, str]) -> DataConfig:
    try:
        if path.stat().st_size > MAX_CONFIG_BYTES:
            raise DataConfigError(f"{path.name}: file too large")
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DataConfigError(f"cannot read {path}: {type(exc).__name__}") from exc
    except yaml.YAMLError as exc:
        raise DataConfigError(f"{path.name}: not valid YAML ({type(exc).__name__})") from exc
    return parse_data_config(raw, env)
