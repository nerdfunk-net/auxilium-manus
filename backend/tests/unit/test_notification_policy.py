"""Notification policy (D11): config errors raise, transport errors are recorded, rows replace."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.models.notifications import Notification
from models.failure import FailureInfo
from models.workflow_context import DeviceContext, DeviceError, WorkflowContext
from repositories.notification_repository import NotificationRepository
from services.mail import smtp_sender
from services.mail.errors import MailSendError
from services.mattermost.client import MattermostService
from services.mattermost.common.exceptions import MattermostAPIError
from services.workflow_context.attribute_path import DEBUG_LOGS_METADATA_SUFFIX
from workflow_steps.common.notification_target import parse_mattermost_target
from workflow_steps.notify import executor as notify_executor
from workflow_steps.notify_mattermost import executor as mm_executor
from workflow_steps.notify_on_error import executor as on_error_executor

_CONTEXT = "workflow_steps.common.notification_context"
_MM = {"mattermost_source_id": "lab", "team_name": "net", "channel_name": "alerts"}


def _row(node_id: str, device: str | None, message: str = "m") -> dict:
    return {
        "run_id": 1,
        "node_id": node_id,
        "workflow_id": 5,
        "workflow_name": "wf",
        "workflow_owner_username": "alice",
        "device_name": device,
        "severity": "info",
        "message": message,
    }


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Notification.__table__.create(engine)
    with Session(engine) as db:
        yield db


def test_replace_for_node_is_idempotent(session) -> None:
    repo = NotificationRepository(session)
    repo.replace_for_node(run_id=1, node_id="n1", rows=[_row("n1", "r1"), _row("n1", None)])
    repo.replace_for_node(run_id=1, node_id="n1", rows=[_row("n1", "r1"), _row("n1", None)])
    assert len(session.scalars(select(Notification)).all()) == 2


def test_replace_for_node_keeps_other_nodes_and_devices(session) -> None:
    repo = NotificationRepository(session)
    repo.replace_for_node(run_id=1, node_id="n1", rows=[_row("n1", "r1")])
    repo.replace_for_node(run_id=1, node_id="n2", rows=[_row("n2", "r1")])
    repo.replace_for_node(run_id=1, node_id="n1", rows=[_row("n1", "r2")])
    pairs = {(n.node_id, n.device_name) for n in session.scalars(select(Notification))}
    assert pairs == {("n1", "r1"), ("n1", "r2"), ("n2", "r1")}


def test_replace_for_node_rolls_back_on_failure() -> None:
    db = MagicMock()
    db.commit.side_effect = RuntimeError("db down")
    with pytest.raises(RuntimeError):
        NotificationRepository(db).replace_for_node(run_id=1, node_id="n", rows=[_row("n", "r")])
    db.rollback.assert_called_once()


def test_parse_mattermost_target() -> None:
    target = parse_mattermost_target(
        {"mattermost_source_id": " lab ", "team_name": "net", "channel_name": "a"},
        step_id="x",
    )
    assert (target.source_id, target.team_name, target.channel_name) == ("lab", "net", "a")
    with pytest.raises(ValueError, match="team_name"):
        parse_mattermost_target({"mattermost_source_id": "lab", "channel_name": "a"}, step_id="x")


def _ctx(errors: bool = True) -> WorkflowContext:
    device = DeviceContext(id="d1", name="r1", hostname="r1")
    if errors:
        device.errors.append(DeviceError(node_id="n", step_id="s", code="c", message="boom"))
    return WorkflowContext(run_id="u", workflow_id="w", devices={"d1": device})


async def _on_error(config: dict, context: WorkflowContext, repo=None, client=None, creds=None):
    run = MagicMock()
    run.id = 1
    repo = repo or MagicMock()
    repo.replace_for_node.side_effect = lambda **kw: [MagicMock() for _ in kw["rows"]]
    wf = MagicMock()
    wf.id = 5
    wf.name = "wf"
    with (
        patch(
            "workflow_steps.notify_on_error.executor.resolve_run_workflow",
            return_value=(wf, "alice"),
        ),
        patch(f"{_CONTEXT}.NotificationRepository", return_value=repo),
        patch("service_factory.get_mattermost_app_service", return_value=client or MagicMock()),
        patch(
            "workflow_steps.notify_on_error.executor.resolve_mattermost_credentials",
            **(creds or {"return_value": MagicMock()}),
        ),
    ):
        return await on_error_executor.execute(
            config=config,
            context=context,
            run=run,
            artifact_service=MagicMock(),
            node_id="oe",
            device_sessions=MagicMock(),
        ), repo


@pytest.mark.asyncio
async def test_notify_on_error_replaces_rows_per_node() -> None:
    _, repo = await _on_error({"message": "{error.message}"}, _ctx())
    kwargs = repo.replace_for_node.call_args.kwargs
    assert (kwargs["run_id"], kwargs["node_id"]) == (1, "oe")
    assert kwargs["rows"][0]["node_id"] == "oe"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [True, 7.9, "x", -1])
async def test_notify_on_error_max_messages_is_strict(bad) -> None:
    with pytest.raises(ValueError, match="max_messages"):
        await _on_error({"message": "m", "max_messages": bad}, _ctx())


@pytest.mark.asyncio
async def test_notify_on_error_unknown_source_raises_even_without_errors() -> None:
    config = {"message": "m", "notify_mattermost": True, **_MM}
    with pytest.raises(ValueError, match="unknown source"):
        await _on_error(
            config, _ctx(errors=False), creds={"side_effect": ValueError("unknown source")}
        )


@pytest.mark.asyncio
async def test_notify_on_error_transport_failure_is_recorded_not_raised() -> None:
    failure = FailureInfo(phase="api", kind="not_found", http_status=404)
    client = MagicMock()
    client.get_channel_by_name = AsyncMock(side_effect=MattermostAPIError("gone", failure=failure))
    config = {"message": "m", "notify_mattermost": True, **_MM}
    outcomes, _ = await _on_error(config, _ctx(), client=client)
    assert outcomes[0].name == "success"
    logs = outcomes[0].context.metadata[f"oe{DEBUG_LOGS_METADATA_SUFFIX}"]
    assert logs["mattermost_failure"] == failure.model_dump(mode="json", exclude_none=True)


@pytest.mark.asyncio
async def test_notify_on_error_post_failure_is_recorded() -> None:
    failure = FailureInfo(phase="api", kind="server_error", http_status=502)
    client = MagicMock()
    client.get_channel_by_name = AsyncMock(return_value={"id": "c"})
    client.create_post = AsyncMock(side_effect=MattermostAPIError("bad", failure=failure))
    config = {"message": "m", "notify_mattermost": True, **_MM}
    outcomes, _ = await _on_error(config, _ctx(), client=client)
    logs = outcomes[0].context.metadata[f"oe{DEBUG_LOGS_METADATA_SUFFIX}"]
    assert logs["mattermost_failed"] == 1
    assert logs["mattermost_failure"]["http_status"] == 502


@pytest.mark.asyncio
async def test_notify_replaces_rows_per_node() -> None:
    repo = MagicMock()
    repo.replace_for_node.side_effect = lambda **kw: [MagicMock() for _ in kw["rows"]]
    wf = MagicMock()
    wf.id = 5
    wf.name = "wf"
    with (
        patch(
            "workflow_steps.notify.executor.resolve_run_workflow",
            return_value=(wf, "alice"),
        ),
        patch(f"{_CONTEXT}.NotificationRepository", return_value=repo),
    ):
        await notify_executor.execute(
            config={"message": "hi"},
            context=_ctx(errors=False),
            run=MagicMock(id=1),
            artifact_service=MagicMock(),
            node_id="nn",
            device_sessions=MagicMock(),
        )
    kwargs = repo.replace_for_node.call_args.kwargs
    assert (kwargs["run_id"], kwargs["node_id"]) == (1, "nn")
    assert kwargs["rows"][0]["node_id"] == "nn"


@pytest.mark.asyncio
async def test_notify_mattermost_failure_outcome_carries_failure_info() -> None:
    failure = FailureInfo(phase="api", kind="permission_denied", http_status=403)
    client = MagicMock()
    client.get_channel_by_name = AsyncMock(side_effect=MattermostAPIError("no", failure=failure))
    with (
        patch("workflow_steps.notify_mattermost.executor.require_session"),
        patch("workflow_steps.notify_mattermost.executor.resolve_mattermost_credentials"),
        patch("service_factory.get_mattermost_app_service", return_value=client),
    ):
        outcomes = await mm_executor.execute(
            config={"message": "m", **_MM},
            context=_ctx(errors=False),
            run=MagicMock(),
            artifact_service=MagicMock(),
            node_id="mm",
            device_sessions=MagicMock(),
        )
    assert outcomes[0].name == "failure"
    assert outcomes[0].failure == failure


@pytest.mark.asyncio
async def test_notify_mattermost_failure_without_classification_still_recorded() -> None:
    client = MagicMock()
    client.get_channel_by_name = AsyncMock(side_effect=MattermostAPIError("plain"))
    with (
        patch("workflow_steps.notify_mattermost.executor.require_session"),
        patch("workflow_steps.notify_mattermost.executor.resolve_mattermost_credentials"),
        patch("service_factory.get_mattermost_app_service", return_value=client),
    ):
        outcomes = await mm_executor.execute(
            config={"message": "m", **_MM},
            context=_ctx(errors=False),
            run=MagicMock(),
            artifact_service=MagicMock(),
            node_id="mm",
            device_sessions=MagicMock(),
        )
    assert outcomes[0].failure is not None
    assert outcomes[0].failure.phase == "api"


def _client_with(response: httpx.Response | Exception) -> MattermostService:
    client = MattermostService()
    if isinstance(response, Exception):
        client._do_request = AsyncMock(side_effect=response)  # type: ignore[method-assign]
    else:
        client._do_request = AsyncMock(return_value=response)  # type: ignore[method-assign]
    client._base_url = AsyncMock(return_value="https://mm")  # type: ignore[method-assign]
    return client


_CREDS = MagicMock(token="t", verify_ssl=True, timeout=5)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (401, "auth_failed"),
        (403, "permission_denied"),
        (404, "not_found"),
        (400, "bad_request"),
        (429, "rate_limited"),
        (502, "server_error"),
    ],
)
async def test_mattermost_client_classifies_status(status: int, kind: str) -> None:
    client = _client_with(httpx.Response(status))
    with pytest.raises(MattermostAPIError) as info:
        await client.create_post(_CREDS, "c", "m")
    assert info.value.failure is not None
    assert (info.value.failure.kind, info.value.failure.http_status) == (kind, status)


@pytest.mark.asyncio
async def test_mattermost_client_classifies_timeout_and_bad_json() -> None:
    with pytest.raises(MattermostAPIError) as info:
        await _client_with(httpx.ReadTimeout("t")).create_post(_CREDS, "c", "m")
    assert info.value.failure is not None and info.value.failure.kind == "timeout"
    with pytest.raises(MattermostAPIError) as info:
        await _client_with(httpx.Response(200, text="<html>")).create_post(_CREDS, "c", "m")
    assert info.value.failure is not None and info.value.failure.kind == "invalid_response"


def test_mail_failure_classification() -> None:
    settings = MagicMock(smtp_server="s", smtp_port=25)
    exc = MagicMock()
    err = smtp_sender._failure(settings, TimeoutError())
    assert err.failure is not None and err.failure.kind == "timeout"

    class Auth(Exception):
        code = 535

    err = smtp_sender._failure(settings, Auth())
    assert err.failure is not None and err.failure.kind == "auth_failed"
    err = smtp_sender._failure(settings, ValueError())
    assert err.failure is not None and err.failure.exception_type == "ValueError"
    del exc


@pytest.mark.asyncio
async def test_send_mail_failure_outcome_carries_failure_info() -> None:
    from workflow_steps.send_mail import executor as mail_executor

    failure = FailureInfo(phase="auth", kind="auth_failed")
    conn = MagicMock(smtp_server="s", from_address="f@x", allowed_recipient_domains=[])
    service = MagicMock()
    service.return_value.connection.return_value = (conn, None, None)
    with (
        patch("workflow_steps.send_mail.executor.MailService", service),
        patch("workflow_steps.send_mail.executor.require_session"),
        patch(
            "workflow_steps.send_mail.executor.smtp_sender.send_message",
            AsyncMock(side_effect=MailSendError("x", failure=failure)),
        ),
    ):
        outcomes = await mail_executor.execute(
            config={"to": "a@b.c", "subject": "s", "body": "b"},
            context=_ctx(errors=False),
            run=MagicMock(),
            artifact_service=MagicMock(),
            node_id="m",
            device_sessions=MagicMock(),
        )
    assert outcomes[0].name == "failure"
    assert outcomes[0].failure == failure


def test_replace_for_node_keeps_other_runs(session) -> None:
    repo = NotificationRepository(session)
    repo.replace_for_node(run_id=1, node_id="n1", rows=[_row("n1", "r1")])
    other = {**_row("n1", "r1"), "run_id": 2}
    repo.replace_for_node(run_id=2, node_id="n1", rows=[other])
    repo.replace_for_node(run_id=1, node_id="n1", rows=[_row("n1", "r1")])
    assert sorted(n.run_id for n in session.scalars(select(Notification))) == [1, 2]


@pytest.mark.asyncio
async def test_notify_overflow_row_carries_node_id() -> None:
    repo = MagicMock()
    repo.replace_for_node.side_effect = lambda **kw: [MagicMock() for _ in kw["rows"]]
    wf = MagicMock()
    wf.id = 5
    wf.name = "wf"
    devices = {
        f"d{i}": DeviceContext(id=f"d{i}", name=f"r{i}", hostname=f"r{i}")
        for i in range(notify_executor.MAX_NOTIFICATIONS_PER_STEP + 3)
    }
    context = WorkflowContext(run_id="u", workflow_id="w", devices=devices)
    with (
        patch(
            "workflow_steps.notify.executor.resolve_run_workflow",
            return_value=(wf, "alice"),
        ),
        patch(f"{_CONTEXT}.NotificationRepository", return_value=repo),
    ):
        await notify_executor.execute(
            config={"message": "hi"},
            context=context,
            run=MagicMock(id=1),
            artifact_service=MagicMock(),
            node_id="nn",
            device_sessions=MagicMock(),
        )
    rows = repo.replace_for_node.call_args.kwargs["rows"]
    assert rows[-1]["device_name"] is None
    assert {row["node_id"] for row in rows} == {"nn"}


@pytest.mark.asyncio
async def test_notify_on_error_unclassified_channel_failure_still_recorded() -> None:
    client = MagicMock()
    client.get_channel_by_name = AsyncMock(side_effect=MattermostAPIError("plain"))
    config = {"message": "m", "notify_mattermost": True, **_MM}
    outcomes, _ = await _on_error(config, _ctx(), client=client)
    logs = outcomes[0].context.metadata[f"oe{DEBUG_LOGS_METADATA_SUFFIX}"]
    assert logs["mattermost_failure"]["phase"] == "api"


@pytest.mark.asyncio
async def test_notify_on_error_summary_post_failure_is_recorded() -> None:
    failure = FailureInfo(phase="api", kind="rate_limited", http_status=429)
    client = MagicMock()
    client.get_channel_by_name = AsyncMock(return_value={"id": "c"})
    client.create_post = AsyncMock(side_effect=MattermostAPIError("slow", failure=failure))
    config = {"message": "m", "notify_mattermost": True, "max_messages": 0, **_MM}
    outcomes, _ = await _on_error(config, _ctx(), client=client)
    logs = outcomes[0].context.metadata[f"oe{DEBUG_LOGS_METADATA_SUFFIX}"]
    assert logs["mattermost_failure"]["http_status"] == 429


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["check_connection", "get_channel_by_name", "create_post"])
async def test_every_client_call_classifies_timeout_and_bad_json(method: str) -> None:
    args = {
        "check_connection": (),
        "get_channel_by_name": ("team", "chan"),
        "create_post": ("c", "m"),
    }[method]
    with pytest.raises(MattermostAPIError) as info:
        await getattr(_client_with(httpx.ReadTimeout("t")), method)(_CREDS, *args)
    assert info.value.failure is not None and info.value.failure.kind == "timeout"
    with pytest.raises(MattermostAPIError) as info:
        await getattr(_client_with(httpx.Response(200, text="<")), method)(_CREDS, *args)
    assert info.value.failure is not None and info.value.failure.kind == "invalid_response"


def test_mail_connection_failure_keeps_exception_type() -> None:
    err = smtp_sender._failure(MagicMock(smtp_server="s", smtp_port=25), ConnectionRefusedError())
    assert err.failure is not None
    assert (err.failure.phase, err.failure.exception_type) == ("connect", "ConnectionRefusedError")
