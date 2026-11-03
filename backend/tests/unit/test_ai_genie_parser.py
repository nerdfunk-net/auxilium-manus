"""The Genie client of the assistant: one pyATS source, as the calling user (§43)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.ai_assistant import genie_parser as gp
from services.ai_assistant.output_parser import ParsedCommand, ParserUnavailableError
from services.pyats.common.exceptions import PyATSAPIError

OUTPUTS = [("show version", "raw text")]


def _patched(*, allowed=True, sources=None, shim=None):
    """Patch the database, RBAC, the source service and the shim for one call."""
    rbac = MagicMock()
    rbac.return_value.has_permission.return_value = allowed
    source_service = MagicMock()
    source_service.return_value.list_sources.return_value = (
        [{"source_id": "lab"}] if sources is None else sources
    )
    source_service.return_value.resolve_credentials.return_value = "creds"
    factory = MagicMock()
    factory.get_pyats_app_service.return_value = shim or MagicMock()
    return (
        patch.object(gp, "SessionLocal", MagicMock()),
        patch.object(gp, "RBACService", rbac),
        patch.object(gp, "PyATSSourceConfigService", source_service),
        patch.object(gp, "service_factory", factory),
        source_service,
        rbac,
    )


def _run(parser: gp.DbGenieParser):
    return asyncio.run(parser.parse("iosxe", OUTPUTS))


def _enter(patches):
    for p in patches[:4]:
        p.start()


def _exit(patches):
    for p in patches[:4]:
        p.stop()


@pytest.fixture
def patches():
    def make(**kw):
        made = _patched(**kw)
        _enter(made)
        return made

    created = []

    def factory(**kw):
        made = make(**kw)
        created.append(made)
        return made

    yield factory
    for made in created:
        _exit(made)


def test_parses_through_the_single_source(patches) -> None:
    shim = MagicMock()
    shim.parse_batch = AsyncMock(
        return_value={
            "results": {
                "device": {
                    "commands": {
                        "show version": {"parsed": {"version": {"hostname": "r1"}}, "error": None}
                    }
                }
            }
        }
    )
    made = patches(shim=shim)
    source_service, rbac = made[4], made[5]

    result = _run(gp.DbGenieParser(user_id=5))

    assert result == [ParsedCommand("show version", {"version": {"hostname": "r1"}}, None)]
    rbac.return_value.has_permission.assert_called_once_with(5, "sources.pyats", "read")
    source_service.return_value.resolve_credentials.assert_called_once_with("lab")
    shim.parse_batch.assert_awaited_once_with(
        "creds",
        timeout_seconds=gp.SHIM_TIMEOUT_SECONDS,
        devices={
            "device": {
                "os": "iosxe",
                "commands": [{"command": "show version", "output": "raw text"}],
            }
        },
    )


def test_a_command_error_from_the_shim_is_kept(patches) -> None:
    shim = MagicMock()
    shim.parse_batch = AsyncMock(
        return_value={
            "results": {
                "device": {"commands": {"show version": {"parsed": None, "error": "no parser"}}}
            }
        }
    )
    patches(shim=shim)

    assert _run(gp.DbGenieParser(user_id=5)) == [
        ParsedCommand("show version", None, gp.GENIE_COULD_NOT_PARSE)
    ]


def test_a_missing_command_in_the_reply_is_an_error(patches) -> None:
    shim = MagicMock()
    shim.parse_batch = AsyncMock(return_value={"results": {}})
    patches(shim=shim)

    with pytest.raises(ParserUnavailableError):
        _run(gp.DbGenieParser(user_id=5))


def test_a_command_missing_from_the_reply_is_an_error_on_that_command(patches) -> None:
    shim = MagicMock()
    shim.parse_batch = AsyncMock(
        return_value={"results": {"device": {"commands": {"show other": {"parsed": {}}}}}}
    )
    patches(shim=shim)

    [entry] = _run(gp.DbGenieParser(user_id=5))

    assert entry.parsed is None
    assert entry.error == gp.NO_SHIM_RESULT


def test_without_the_permission_nothing_is_called(patches) -> None:
    shim = MagicMock()
    shim.parse_batch = AsyncMock()
    patches(allowed=False, shim=shim)

    with pytest.raises(ParserUnavailableError, match="not allowed"):
        _run(gp.DbGenieParser(user_id=5))

    shim.parse_batch.assert_not_awaited()


def test_no_source_is_unavailable(patches) -> None:
    patches(sources=[])

    with pytest.raises(ParserUnavailableError, match="No pyATS source"):
        _run(gp.DbGenieParser(user_id=5))


def test_several_sources_are_unavailable(patches) -> None:
    patches(sources=[{"source_id": "a"}, {"source_id": "b"}])

    with pytest.raises(ParserUnavailableError, match="more than one"):
        _run(gp.DbGenieParser(user_id=5))


def test_a_shim_failure_is_unavailable_with_a_fixed_text(patches) -> None:
    shim = MagicMock()
    shim.parse_batch = AsyncMock(side_effect=PyATSAPIError("secret detail 10.0.0.1"))
    patches(shim=shim)

    with pytest.raises(ParserUnavailableError) as raised:
        _run(gp.DbGenieParser(user_id=5))

    assert "10.0.0.1" not in str(raised.value)
    assert str(raised.value) == gp.SHIM_FAILED


def test_has_pyats_source_is_true_for_one_source_and_false_otherwise(patches) -> None:
    patches()
    assert gp.has_pyats_source(5) is True


def test_has_pyats_source_is_false_for_none_several_or_no_permission(patches) -> None:
    for kwargs in (
        {"sources": []},
        {"sources": [{"source_id": "a"}, {"source_id": "b"}]},
        {"allowed": False},
    ):
        made = patches(**kwargs)
        assert gp.has_pyats_source(5) is False
        _exit(made)


def test_the_shims_error_text_is_never_passed_on(patches) -> None:
    shim = MagicMock()
    shim.parse_batch = AsyncMock(
        return_value={
            "results": {
                "device": {
                    "commands": {
                        "show version": {"parsed": None, "error": "bad line: enable secret 5 abc"}
                    }
                }
            }
        }
    )
    patches(shim=shim)

    [entry] = _run(gp.DbGenieParser(user_id=5))

    assert entry.error == gp.GENIE_COULD_NOT_PARSE
    assert "secret" not in entry.error


@pytest.mark.parametrize(
    "answer",
    [
        {"parsed": "a string", "error": None},  # not a dict or list
        {"parsed": None, "error": None},
        {"parsed": {"x": 1}, "error": {"not": "a string"}},  # a non-string error still fails fixed
        "not even a dict",
    ],
)
def test_an_unusable_command_answer_is_a_fixed_error(patches, answer) -> None:
    shim = MagicMock()
    shim.parse_batch = AsyncMock(
        return_value={"results": {"device": {"commands": {"show version": answer}}}}
    )
    patches(shim=shim)

    [entry] = _run(gp.DbGenieParser(user_id=5))

    assert entry.parsed is None
    assert entry.error in (gp.GENIE_COULD_NOT_PARSE, gp.NO_SHIM_RESULT)


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        "x",
        {"results": None},
        {"results": {"device": []}},
        {"results": {"device": {"commands": []}}},
    ],
)
def test_a_misshapen_body_is_unavailable_not_an_attribute_error(patches, body) -> None:
    shim = MagicMock()
    shim.parse_batch = AsyncMock(return_value=body)
    patches(shim=shim)

    with pytest.raises(ParserUnavailableError) as raised:
        _run(gp.DbGenieParser(user_id=5))

    assert str(raised.value) == gp.SHIM_FAILED


def test_a_200_that_is_not_json_is_unavailable(patches) -> None:
    shim = MagicMock()
    shim.parse_batch = AsyncMock(side_effect=ValueError("Expecting value: line 1 column 1"))
    patches(shim=shim)

    with pytest.raises(ParserUnavailableError) as raised:
        _run(gp.DbGenieParser(user_id=5))

    assert str(raised.value) == gp.SHIM_FAILED
