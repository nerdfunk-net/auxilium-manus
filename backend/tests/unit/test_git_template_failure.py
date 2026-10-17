"""Git and template failures -> structured FailureInfo."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from git.exc import GitCommandError

from core.safe_urls import UnsafeURLError
from models.failure import FailureInfo, failure_from_exception
from models.workflow_context import DeviceContext, DeviceStatus, WorkflowContext
from services.git.failure import (
    GitOperationError,
    annotate_failure,
    classify_git_exception,
    classify_git_text,
)
from services.git.service import GitService, PullResult, PushResult
from workflow_steps.common.jinja_render import JinjaTemplateError, render_jinja_template
from workflow_steps.git_pull.executor import execute as git_pull


@pytest.mark.parametrize(
    ("text", "kind", "hint"),
    [
        (
            "fatal: unable to access 'x': Could not resolve host: git.example",
            "dns",
            "check_hostname",
        ),
        ("fatal: unable to connect: Connection refused", "refused", "check_reachability"),
        ("fatal: Connection timed out", "timeout", "check_reachability"),
        ("fatal: Authentication failed for 'https://h/r.git'", "auth_failed", "check_credentials"),
        ("fatal: could not read Username for 'https://h'", "auth_failed", "check_credentials"),
        ("The requested URL returned error: 403", "permission_denied", "check_permissions"),
        ("! [rejected] main -> main (fetch first)", "push_rejected", "pull_first"),
        ("CONFLICT (content): Merge conflict in a.cfg", "merge_conflict", "resolve_conflict"),
        ("fatal: repository 'https://h/r.git' not found", "not_found", "check_request"),
        ("fatal: Unable to create '.git/index.lock': File exists", "repo_locked", None),
        ("SSL certificate problem: self signed certificate", "tls_error", "check_tls"),
        ("fatal: Host key verification failed.", "ssh_error", "check_ssh_compatibility"),
        ("something else entirely", "unknown", None),
    ],
)
def test_text_classification(text: str, kind: str, hint: str | None) -> None:
    failure = classify_git_text(text)

    assert (failure.phase, failure.kind) == ("git", kind)
    if hint is not None:
        assert failure.hint == hint


def test_git_command_error_without_known_cause_is_command_error() -> None:
    exc = GitCommandError(["git", "pull"], 1, stderr="odd failure")

    assert classify_git_exception(exc).kind == "command_error"


def test_classification_never_contains_the_message() -> None:
    exc = GitCommandError(
        ["git", "push"], 128, stderr="Authentication failed for https://user:tok3n@h/r.git"
    )

    dumped = classify_git_exception(exc).model_dump_json()

    assert "tok3n" not in dumped
    assert "user" not in dumped


def test_unsafe_url_and_timeouts() -> None:
    assert classify_git_exception(UnsafeURLError("blocked")).kind == "bad_request"
    assert classify_git_exception(TimeoutError()).kind == "timeout"
    assert classify_git_exception(TimeoutError()).retryable


def test_annotate_failure_survives_wrapping() -> None:
    original = GitCommandError(["git", "clone"], 128, stderr="Could not resolve host: x")
    try:
        try:
            raise annotate_failure(original)
        except GitCommandError as exc:
            raise RuntimeError("Failed to clone") from exc
    except RuntimeError as wrapped:
        failure = failure_from_exception(wrapped)

    assert failure is not None
    assert failure.kind == "dns"


def test_failed_results_carry_a_failure() -> None:
    service = GitService.__new__(GitService)
    service._auth = MagicMock()
    err = GitCommandError(["git", "pull"], 1, stderr="CONFLICT (content): Merge conflict")
    with patch("services.git.service.validate_git_remote_url", side_effect=err):
        result = service.pull({"url": "https://h/r.git", "branch": "main"})

    assert not result.success
    assert result.failure is not None
    assert result.failure.kind == "merge_conflict"
    raised = result.error()
    assert isinstance(raised, GitOperationError)
    assert isinstance(raised, RuntimeError)
    assert raised.failure == result.failure


def test_push_info_error_is_classified() -> None:
    assert classify_git_text("[remote rejected] main -> main (hook declined)").kind == (
        "push_rejected"
    )
    assert PushResult(success=True, message="ok").failure is None


def _context() -> WorkflowContext:
    return WorkflowContext(
        run_id="r",
        workflow_id="w",
        devices={
            "d1": DeviceContext(id="d1", name="d1", hostname="d1", status=DeviceStatus.OK),
        },
    )


def _run_pull(pull_result: PullResult) -> list:
    git_service = MagicMock()
    git_service.pull.return_value = pull_result
    run = MagicMock()
    run.id = 1
    with (
        patch(
            "workflow_steps.common.git_workflow_step.load_git_repository",
            return_value={"id": 7, "name": "r", "url": "https://h/r.git", "branch": "main"},
        ),
        patch("service_factory.build_git_service", return_value=git_service),
    ):
        return asyncio.run(
            git_pull(
                config={"git_repository_id": 7},
                context=_context(),
                run=run,
                artifact_service=MagicMock(),
                node_id="n1",
                device_sessions=MagicMock(),
            )
        )


def test_git_pull_failure_reaches_outcome_and_devices() -> None:
    info = FailureInfo(phase="git", kind="auth_failed", hint="check_credentials")
    outcomes = _run_pull(PullResult(success=False, message="Pull failed", failure=info))

    failure_outcome = next(o for o in outcomes if o.name == "failure")
    assert failure_outcome.failure == info
    assert failure_outcome.context.devices["d1"].errors[0].failure == info


def test_git_pull_unclassified_exception_is_still_classified() -> None:
    git_service = MagicMock()
    git_service.pull.side_effect = GitCommandError(["git"], 1, stderr="Connection refused")
    with (
        patch(
            "workflow_steps.common.git_workflow_step.load_git_repository",
            return_value={"id": 7, "name": "r", "url": "https://h/r.git", "branch": "main"},
        ),
        patch("service_factory.build_git_service", return_value=git_service),
    ):
        outcomes = asyncio.run(
            git_pull(
                config={"git_repository_id": 7},
                context=_context(),
                run=MagicMock(id=1),
                artifact_service=MagicMock(),
                node_id="n1",
                device_sessions=MagicMock(),
            )
        )

    assert next(o for o in outcomes if o.name == "failure").failure.kind == "refused"


def test_git_pull_bad_repository_is_a_setup_problem() -> None:
    with patch(
        "workflow_steps.common.git_workflow_step.load_git_repository",
        side_effect=ValueError("Git repository 7 not found"),
    ):
        outcomes = asyncio.run(
            git_pull(
                config={"git_repository_id": 7},
                context=_context(),
                run=MagicMock(id=1),
                artifact_service=MagicMock(),
                node_id="n1",
                device_sessions=MagicMock(),
            )
        )

    assert next(o for o in outcomes if o.name == "failure").failure.kind == "bad_request"


# -- templates --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("template", "kind", "line"),
    [
        ("hello\n{{ a.b.c }}", "undefined_variable", 2),
        ("\n\nhello\n{{ a.b.c }}\nx", "undefined_variable", 4),
        ("a\n{% if %}\n", "template_syntax", 2),
        ("a\nb\n{{ 1 / 0 }}", "template_error", 3),
    ],
)
def test_template_failures(template: str, kind: str, line: int) -> None:
    with pytest.raises(JinjaTemplateError) as info:
        render_jinja_template(template, {"a": {}})

    failure = info.value.failure
    assert failure is not None
    assert (failure.phase, failure.kind, failure.line, failure.hint) == (
        "render",
        kind,
        line,
        "fix_template",
    )


def test_template_failure_has_no_variable_text() -> None:
    with pytest.raises(JinjaTemplateError) as info:
        render_jinja_template("{{ secret_value_name.attr }}", {})

    assert "secret_value_name" not in info.value.failure.model_dump_json()
    assert failure_from_exception(info.value) is info.value.failure
