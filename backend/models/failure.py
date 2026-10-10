"""Structured, non-sensitive description of *why* an operation failed.

Free-text error messages can echo device output, hostnames or credentials, so the AI
assistant only sees them with the user's content opt-in (``doc/ai_integration/AI_ASSISTANT.md``
§4). ``FailureInfo`` is the part that is safe without it: every field is a member of a closed
vocabulary, a number or an exception class name, never text taken from the device or a request.
Do not add a free-text field here.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

FailurePhase = Literal[
    "connect",  # opening a session (SSH)
    "command",
    "config",
    "transfer",
    "auth",  # obtaining a token / logging in to an API
    "api",  # one request/response against a REST API
    "task",  # an asynchronous job on a controller
    "internal",  # a bug in our own code
    "render",  # rendering a Jinja template
    "git",  # a git operation (clone, pull, push, commit, fetch)
]

FailureKind = Literal[
    "timeout",  # no answer within the connect timeout
    "refused",  # TCP connection actively refused (nothing listening on the SSH port)
    "dns",  # hostname did not resolve
    "no_route",  # host or network unreachable
    "auth_failed",  # credentials rejected
    "ssh_error",  # SSH negotiation failed (algorithms, host key, banner)
    "command_timeout",  # device connected but did not return to the prompt in time
    "config_rejected",  # device refused the configuration
    "command_error",  # command or session failed after connecting
    "tls_error",  # TLS handshake or certificate verification failed
    "permission_denied",  # authenticated, but the request was refused (401/403 after login)
    "rate_limited",  # HTTP 429 after the bounded retries
    "not_found",  # HTTP 404
    "bad_request",  # the API rejected the request (HTTP 400) or our input
    "server_error",  # HTTP 5xx
    "invalid_response",  # the API answered with something we could not use
    "task_failed",  # an asynchronous job reported failure
    "task_timeout",  # an asynchronous job did not finish in time
    "command_blocked",  # the controller refused to run the command (blocklist)
    "already_exists",  # the object to create is already there
    "push_rejected",  # the remote refused the push (non-fast-forward, hooks)
    "merge_conflict",  # pulling produced conflicts or would overwrite local changes
    "repo_locked",  # the working tree is in use by another run / git process
    "template_syntax",  # the template does not parse
    "undefined_variable",  # the template used a name or attribute the context does not have
    "template_error",  # the template failed while rendering (filter, type, sandbox)
    "internal_error",  # unexpected exception in our own code; only the class name is kept
    "unknown",
]

# Stable codes a caller can map to advice; deliberately not prose.
FailureHint = Literal[
    "check_reachability",
    "check_hostname",
    "check_ssh_service",
    "check_credentials",
    "check_ssh_compatibility",
    "increase_read_timeout",
    "check_command_syntax",
    "check_tls",
    "check_permissions",
    "check_request",
    "check_controller",
    "retry_later",
    "fix_template",
    "pull_first",
    "resolve_conflict",
    "wait_for_other_run",
]


class FailureInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    phase: FailurePhase
    kind: FailureKind
    retryable: bool = False
    attempts: int | None = None
    max_attempts: int | None = None
    elapsed_ms: int | None = None
    # HTTP status of the API answer, when there was one.
    http_status: int | None = None
    # Line of the template (1-based, as the author sees it) where a render failed.
    line: int | None = None
    # Class name of the exception that was classified (e.g. "NetmikoTimeoutException").
    exception_type: str | None = None
    hint: FailureHint | None = None


_MAX_CHAIN_DEPTH = 5


def failure_from_exception(exc: BaseException) -> FailureInfo | None:
    """The classification an exception carries (``NetmikoConnectionError.failure``), if any.

    Follows ``__cause__`` / ``__context__`` so ``raise RuntimeError(...) from exc`` keeps the
    classification of the original client error.
    """
    current: BaseException | None = exc
    for _ in range(_MAX_CHAIN_DEPTH):
        if current is None:
            return None
        failure = getattr(current, "failure", None)
        if isinstance(failure, FailureInfo):
            return failure
        current = current.__cause__ or current.__context__
    return None


def failure_to_json(failure: FailureInfo | None) -> dict[str, object] | None:
    """JSON form stored on ``WorkflowStepResult.failure`` (unset fields omitted)."""
    return failure.model_dump(mode="json", exclude_none=True) if failure is not None else None


def failure_for_step_exception(exc: BaseException, *, category: str) -> FailureInfo | None:
    """The record for a step that raised: the carried classification, else, for an
    ``internal`` error (a bug), just the exception class name."""
    failure = failure_from_exception(exc)
    if failure is not None:
        return failure
    if category == "internal":
        return FailureInfo(
            phase="internal", kind="internal_error", exception_type=type(exc).__name__
        )
    return None
