"""Classify git failures into a :class:`models.failure.FailureInfo`.

git reports most causes only as text on stderr, so the text is *inspected* to pick a kind; it is
never copied into the record (it can contain remote URLs and branch names).
"""

from __future__ import annotations

import subprocess

from git.exc import GitCommandError

from core.safe_urls import UnsafeURLError
from models.failure import FailureHint, FailureInfo, FailureKind
from services.network.transport_failure import transport_kind

# (needles in the lower-cased text, kind); first match wins, so order matters.
_TEXT_CAUSES: tuple[tuple[tuple[str, ...], FailureKind], ...] = (
    (("could not resolve host", "name or service not known"), "dns"),
    (("connection refused",), "refused"),
    (("timed out", "timeout"), "timeout"),
    (("no route to host", "network is unreachable"), "no_route"),
    (
        ("ssl certificate", "certificate verify", "ssl connect error", "tls connect error"),
        "tls_error",
    ),
    (("host key verification failed",), "ssh_error"),
    (
        (
            "authentication failed",
            "could not read username",
            "could not read password",
            "invalid username or password",
            "permission denied (publickey",
            "terminal prompts disabled",
            "returned error: 401",
            "authentication",
        ),
        "auth_failed",
    ),
    (
        (
            "returned error: 403",
            "permission to ",
            "access denied",
            "protected branch",
            "remote: permission",
        ),
        "permission_denied",
    ),
    (
        ("non-fast-forward", "fetch first", "[rejected]", "failed to push some refs", "rejected"),
        "push_rejected",
    ),
    (
        ("automatic merge failed", "would be overwritten by merge", "conflict", "unmerged"),
        "merge_conflict",
    ),
    (
        (
            "repository not found",
            "' not found",
            "does not appear to be a git repository",
            "returned error: 404",
            "couldn't find remote ref",
            "invalid reference",
        ),
        "not_found",
    ),
    (("index.lock", "another git process"), "repo_locked"),
)

_HINTS: dict[FailureKind, FailureHint] = {
    "dns": "check_hostname",
    "refused": "check_reachability",
    "timeout": "check_reachability",
    "no_route": "check_reachability",
    "tls_error": "check_tls",
    "ssh_error": "check_ssh_compatibility",
    "auth_failed": "check_credentials",
    "permission_denied": "check_permissions",
    "push_rejected": "pull_first",
    "merge_conflict": "resolve_conflict",
    "not_found": "check_request",
    "bad_request": "check_request",
    "repo_locked": "wait_for_other_run",
}

_RETRYABLE: frozenset[FailureKind] = frozenset({"timeout", "no_route", "repo_locked"})


def _build(kind: FailureKind, exc: BaseException | None) -> FailureInfo:
    return FailureInfo(
        phase="git",
        kind=kind,
        retryable=kind in _RETRYABLE,
        exception_type=type(exc).__name__ if exc is not None else None,
        hint=_HINTS.get(kind),
    )


def classify_git_text(text: str, *, exc: BaseException | None = None) -> FailureInfo:
    """Classify git output (stderr of a failed command, or a push-info summary)."""
    lowered = text.lower()
    for needles, kind in _TEXT_CAUSES:
        if any(needle in lowered for needle in needles):
            return _build(kind, exc)
    return _build("command_error" if isinstance(exc, GitCommandError) else "unknown", exc)


def classify_git_exception(exc: BaseException) -> FailureInfo:
    if isinstance(exc, UnsafeURLError):
        return _build("bad_request", exc)
    if isinstance(exc, (subprocess.TimeoutExpired, TimeoutError)):
        return _build("timeout", exc)
    transport = transport_kind(exc)
    if transport is not None and not isinstance(exc, GitCommandError):
        return _build(transport, exc)
    return classify_git_text(str(exc), exc=exc)


def annotate_failure[E: BaseException](exc: E) -> E:
    """Attach the classification to *exc* itself (once) and return it.

    For exceptions we do not own (GitPython's) that are re-raised unchanged: callers that wrap
    them later (``raise RuntimeError(...) from exc``) keep the record through the cause chain.
    """
    if getattr(exc, "failure", None) is None:
        exc.failure = classify_git_exception(exc)  # type: ignore[attr-defined]
    return exc


class GitOperationError(RuntimeError):
    """A git operation failed; ``failure`` says why (see ``models.failure``)."""

    def __init__(self, message: str, *, failure: FailureInfo | None = None) -> None:
        super().__init__(message)
        self.failure = failure
