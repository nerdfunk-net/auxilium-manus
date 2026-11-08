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


def test_empty_output_is_reported_as_no_output_and_not_sent_to_the_shim(patches) -> None:
    shim = MagicMock()
    shim.parse_batch = AsyncMock(
        return_value={
            "results": {
                "device": {"commands": {"show version": {"parsed": {"v": 1}, "error": None}}}
            }
        }
    )
    patches(shim=shim)

    result = asyncio.run(
        gp.DbGenieParser(7).parse(
            "iosxe", [("show version", "raw"), ("show bgp all cluster-ids", "  \n")]
        )
    )

    assert result == [
        ParsedCommand("show version", {"v": 1}, None),
        ParsedCommand("show bgp all cluster-ids", None, gp.NO_OUTPUT),
    ]
    sent = shim.parse_batch.call_args.kwargs["devices"]["device"]["commands"]
    assert [c["command"] for c in sent] == ["show version"]


def test_only_empty_outputs_never_call_the_shim(patches) -> None:
    shim = MagicMock()
    shim.parse_batch = AsyncMock()
    patches(shim=shim)

    result = asyncio.run(gp.DbGenieParser(7).parse("iosxe", [("show x", "")]))

    assert result == [ParsedCommand("show x", None, gp.NO_OUTPUT)]
    shim.parse_batch.assert_not_called()


_DAMPENING = (
    "For address family: IPv4 Unicast\n\n% dampening not enabled for base\n\n"
    "For address family: L2VPN E-VPN\n\n% dampening not enabled for base\n"
)


@pytest.mark.parametrize(
    "output",
    [
        "No templates configured",
        _DAMPENING,
        "Cluster-id     #-neighbors C2C-rfl-CFG C2C-rfl-USE",
    ],
)
def test_nothing_configured_messages_are_recognised(output: str) -> None:
    assert gp.nothing_configured(output)


@pytest.mark.parametrize(
    "output",
    ["", "   \n", "No templates configured\nTemplate peer-policy X", "% Invalid input", "x"],
)
def test_other_text_is_not_nothing_configured(output: str) -> None:
    assert not gp.nothing_configured(output)


def test_failed_parse_of_a_nothing_configured_output_gets_the_clear_message(patches) -> None:
    shim = MagicMock()
    shim.parse_batch = AsyncMock(
        return_value={
            "results": {
                "device": {
                    "commands": {
                        "show ip bgp template peer-policy": {"parsed": None, "error": "boom"},
                        "show bad": {"parsed": None, "error": "boom"},
                    }
                }
            }
        }
    )
    patches(shim=shim)

    result = asyncio.run(
        gp.DbGenieParser(7).parse(
            "iosxe",
            [("show ip bgp template peer-policy", "No templates configured"), ("show bad", "junk")],
        )
    )

    assert [r.error for r in result] == [gp.NOT_CONFIGURED, gp.GENIE_COULD_NOT_PARSE]


def test_a_real_parse_wins_over_the_nothing_configured_check(patches) -> None:
    shim = MagicMock()
    shim.parse_batch = AsyncMock(
        return_value={
            "results": {"device": {"commands": {"show x": {"parsed": {"a": 1}, "error": None}}}}
        }
    )
    patches(shim=shim)

    result = asyncio.run(
        gp.DbGenieParser(7).parse("iosxe", [("show x", "No templates configured")])
    )

    assert result == [ParsedCommand("show x", {"a": 1}, None)]


_TOTAL_CMD = "show bgp all neighbors 192.0.2.1 advertised-routes | include Total number of prefixes"


def test_prefix_total_is_read_locally_and_never_sent_to_the_shim(patches) -> None:
    shim = MagicMock()
    shim.parse_batch = AsyncMock(
        return_value={
            "results": {"device": {"commands": {"show x": {"parsed": {"v": 1}, "error": None}}}}
        }
    )
    patches(shim=shim)

    result = asyncio.run(
        gp.DbGenieParser(7).parse(
            "iosxe",
            [
                ("show x", "raw"),
                (_TOTAL_CMD, "Total number of prefixes 3 \n"),
                (
                    "show bgp all neighbors 192.0.2.1 received-routes | count",
                    "Number of lines which match regexp = 9",
                ),
                ("show y | include Total number of prefixes", ""),
            ],
        )
    )

    assert result[0] == ParsedCommand("show x", {"v": 1}, None)
    assert result[1] == ParsedCommand(_TOTAL_CMD, {"total_prefixes": 3}, None)
    assert result[2].parsed == {"matching_lines": 9}
    assert result[3].error == gp.NO_TOTAL  # no total printed: not "nothing configured"
    sent = shim.parse_batch.call_args.kwargs["devices"]["device"]["commands"]
    assert [c["command"] for c in sent] == ["show x"]


def test_only_filtered_totals_never_call_the_shim(patches) -> None:
    shim = MagicMock()
    shim.parse_batch = AsyncMock()
    patches(shim=shim)

    result = asyncio.run(
        gp.DbGenieParser(7).parse("iosxe", [(_TOTAL_CMD, "Total number of prefixes 0")])
    )

    assert result[0].parsed == {"total_prefixes": 0}
    shim.parse_batch.assert_not_called()


def test_other_commands_are_not_treated_as_totals() -> None:
    assert gp.filtered_total("show version", "Total number of prefixes 3") is None


def test_learn_replay_returns_the_models_payload(patches) -> None:
    shim = MagicMock()
    shim.learn_replay = AsyncMock(
        return_value={"payload": {"info": {"instance": {}}, "_exclude": []}, "error": None}
    )
    patches(shim=shim)

    payload = asyncio.run(
        gp.DbGenieParser(7).learn_replay("iosxe", "bgp", [("show bgp all summary", "raw")])
    )

    assert payload["info"] == {"instance": {}}
    kwargs = shim.learn_replay.call_args.kwargs
    assert kwargs["feature"] == "bgp" and kwargs["os_name"] == "iosxe"
    assert kwargs["commands"] == [{"command": "show bgp all summary", "output": "raw"}]


@pytest.mark.parametrize(
    "answer", [{"payload": None, "error": "Genie could not learn x"}, {}, {"payload": {"info": 3}}]
)
def test_learn_replay_without_a_model_is_a_fixed_error(patches, answer) -> None:
    shim = MagicMock()
    shim.learn_replay = AsyncMock(return_value=answer)
    patches(shim=shim)

    with pytest.raises(ParserUnavailableError) as raised:
        asyncio.run(gp.DbGenieParser(7).learn_replay("iosxe", "bgp", []))

    assert str(raised.value) == gp.LEARN_FAILED


def test_learn_replay_and_diff_hide_transport_errors(patches) -> None:
    shim = MagicMock()
    shim.learn_replay = AsyncMock(side_effect=PyATSAPIError("secret detail"))
    shim.diff = AsyncMock(side_effect=PyATSAPIError("secret detail"))
    patches(shim=shim)
    parser = gp.DbGenieParser(7)

    with pytest.raises(ParserUnavailableError) as first:
        asyncio.run(parser.learn_replay("iosxe", "bgp", []))
    with pytest.raises(ParserUnavailableError) as second:
        asyncio.run(parser.diff_models({}, {}, []))

    assert str(first.value) == gp.SHIM_FAILED and str(second.value) == gp.SHIM_FAILED


def test_diff_models_sends_the_noise_keys_as_the_callers_exclude(patches) -> None:
    shim = MagicMock()
    shim.diff = AsyncMock(
        return_value={"identical": False, "diff": "-a\n+b", "excluded": ["up_time"]}
    )
    patches(shim=shim)

    answer = asyncio.run(gp.DbGenieParser(7).diff_models({"info": 1}, {"info": 2}, ["up_time"]))

    assert answer["identical"] is False
    kwargs = shim.diff.call_args.kwargs
    assert kwargs["exclude_keys"] == ["up_time"]
    assert kwargs["snapshot_a"] == {"info": 1} and kwargs["snapshot_b"] == {"info": 2}
