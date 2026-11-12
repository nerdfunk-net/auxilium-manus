"""The confirm-time executor for a proposed device command (doc/AI_TOOL_CHAIN.md §29 step 5)."""

from __future__ import annotations

import asyncio
import logging

import pytest

from core.config import settings
from services.ai_assistant import device_exec_service as ex
from services.ai_assistant.command_policy import CommandNotAllowedError
from services.ai_assistant.data_sharing import DataClass
from services.ai_assistant.device_access import (
    DeviceCommandOutput,
    DeviceNotFoundError,
    ResolvedDevice,
)
from services.ai_assistant.device_token import issue_token
from services.ai_assistant.results.store import InMemoryResultBackend, ResultStore

USER = 7
DEVICE = ResolvedDevice("nb1", "dev-1", "LAB", "10.1.2.3", "cisco_ios", "cisco_ios")


@pytest.fixture(autouse=True)
def _secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "secret_key", "k" * 40)


class FakeResolver:
    def __init__(self, device=DEVICE, error=None) -> None:
        self.device, self.error, self.names = device, error, []

    async def resolve(self, name):
        self.names.append(name)
        if self.error:
            raise self.error
        return self.device


class FakeRunner:
    def __init__(self, output=None) -> None:
        self.output = output or DeviceCommandOutput(
            True, None, (("show running-config", "hostname LAB\nenable password hunter2xx\n"),)
        )
        self.calls = []
        self.drivers = []
        self.drivers = []

    async def run(self, device, commands, *, credential_id, user_id, network_driver=None):
        self.drivers.append(network_driver)
        self.calls.append((device, commands, credential_id, user_id))
        return self.output


def _token(commands=("show running-config",), **kw) -> str:
    args = {
        "user_id": USER,
        "source_id": "nb1",
        "device_id": "dev-1",
        "device_name": "LAB",
        "host": "10.1.2.3",
        "commands": list(commands),
    }
    args.update(kw)
    return issue_token(**args)[0]


def _executor(resolver=None, runner=None, store="default", secrets=()):
    store = ResultStore(InMemoryResultBackend()) if store == "default" else store
    return ex.DeviceCommandExecutor(
        resolver or FakeResolver(),
        runner or FakeRunner(),
        store,
        secret_loader=lambda user_id: list(secrets) if secrets is not None else None,
    )


def _run(executor, token=None, credential_id=11, user_id=USER, network_driver=None):
    return asyncio.run(
        executor.execute(
            user_id=user_id,
            token=token or _token(),
            credential_id=credential_id,
            network_driver=network_driver,
        )
    )


def test_happy_path_runs_on_the_resolved_device_with_the_users_credential() -> None:
    runner = FakeRunner()

    result = _run(_executor(runner=runner))

    assert runner.calls == [(DEVICE, ["show running-config"], 11, USER)]
    assert result.success and result.device_name == "LAB"
    assert result.commands == ("show running-config",)
    assert "hostname LAB" in result.output


def test_the_output_is_redacted_before_it_is_returned_or_stored() -> None:
    store = ResultStore(InMemoryResultBackend())
    result = _run(_executor(store=store, secrets=["hunter2xx"]))

    stored = asyncio.run(store.get(USER, result.handle))

    assert "hunter2xx" not in result.output
    assert stored is not None and "hunter2xx" not in (stored.text or "")
    assert stored.data_class is DataClass.CONTENT
    assert stored.kind == "device_command"
    assert "hostname LAB" in (stored.text or "")


def test_the_stored_text_names_each_command() -> None:
    runner = FakeRunner(
        DeviceCommandOutput(True, None, (("show version", "IOS 15"), ("show clock", "12:00")))
    )
    result = _run(_executor(runner=runner), _token(["show version", "show clock"]))

    assert "$ show version\nIOS 15" in result.output
    assert "$ show clock\n12:00" in result.output


def test_without_a_result_store_there_is_no_handle_but_the_output_is_returned() -> None:
    result = _run(_executor(store=None))

    assert result.handle is None
    assert "hostname LAB" in result.output


def test_a_store_that_is_down_degrades_to_no_handle() -> None:
    from services.ai_assistant.results.store import ResultStoreUnavailableError

    class Down(ResultStore):
        async def put(self, user_id, result):
            raise ResultStoreUnavailableError

    result = _run(_executor(store=Down(InMemoryResultBackend())))

    assert result.handle is None and result.success


# -- refusals ---------------------------------------------------------------------------------


def test_a_forged_or_foreign_token_never_reaches_the_device() -> None:
    runner = FakeRunner()
    resolver = FakeResolver()

    with pytest.raises(ex.InvalidConfirmationError):
        _run(_executor(resolver, runner), "garbage")
    with pytest.raises(ex.InvalidConfirmationError):
        _run(_executor(resolver, runner), _token(), user_id=8)
    with pytest.raises(ex.InvalidConfirmationError):
        _run(_executor(resolver, runner), _token(user_id=8))

    assert runner.calls == [] and resolver.names == []


def test_an_expired_token_is_refused(monkeypatch) -> None:
    token = _token()
    from services.ai_assistant import device_token

    monkeypatch.setattr(device_token.time, "time", lambda: 10**12)

    with pytest.raises(ex.InvalidConfirmationError):
        _run(_executor(), token)


def test_the_policy_runs_again_on_the_signed_commands() -> None:
    # A token signed by a buggy or older proposer with a command the policy now refuses.
    runner = FakeRunner()
    with pytest.raises(CommandNotAllowedError):
        _run(_executor(runner=runner), _token(["reload"]))
    with pytest.raises(ex.InvalidConfirmationError):
        _run(_executor(runner=runner), _token(["show  version"]))  # not in normalised form

    assert runner.calls == []


def test_a_signed_ping_and_traceroute_run_but_other_verbs_never_do() -> None:
    # doc/AI_TOOL_CHAIN.md §51: probes built by the catalogue pass the confirm step.
    runner = FakeRunner()
    commands = ["ping 192.168.178.241 repeat 5 timeout 2", "traceroute 192.168.178.241"]

    result = _run(_executor(runner=runner), _token(commands))

    assert result.commands == tuple(commands)
    assert runner.calls == [(DEVICE, commands, 11, USER)]
    refused = (["ping example.com"], ["ping 127.0.0.1"], ["telnet 10.0.0.1"], ["ping 10.0.0.1 | x"])
    for bad in refused:
        with pytest.raises(CommandNotAllowedError):
            _run(_executor(runner=runner), _token(bad))
    assert len(runner.calls) == 1


def test_a_probe_run_that_timed_out_keeps_what_finished_for_the_assistant() -> None:
    # The ping finished, the traceroute hit the read timeout: the ping output is stored (a handle),
    # the run still reports the failure (doc/analysis/REVIEW.md, issue 1).
    ping, trace = "ping 192.168.178.241 repeat 5 timeout 2", "traceroute 192.168.178.241"
    runner = FakeRunner(DeviceCommandOutput(False, "timed out", ((ping, "5/5 ok"), (trace, ""))))

    result = _run(_executor(runner=runner), _token([ping, trace]))

    assert not result.success and result.handle is not None
    assert "5/5 ok" in result.output


def test_a_show_run_that_timed_out_still_gets_no_handle() -> None:
    partial = FakeRunner(DeviceCommandOutput(False, "timeout", (("show version", "half"),)))

    assert _run(_executor(runner=partial), _token(["show version"])).handle is None


def test_ping_and_traceroute_get_the_long_read_timeout() -> None:
    from services.ai_assistant.device_access import long_command_count

    commands = ["ping 10.0.0.1 repeat 5", "traceroute 10.0.0.1", "show version"]
    assert long_command_count(commands) == 2


def test_more_than_five_commands_run_only_when_they_are_a_catalogue_plan() -> None:
    from services.ai_assistant.learn import catalogue

    plan = catalogue.plan_learn("ios", "ospf").commands
    runner = FakeRunner()

    _run(_executor(runner=runner), _token(plan))
    assert runner.calls[0][1] == list(plan)

    other = FakeRunner()
    for commands in ([f"show version {i}" for i in range(6)], [*plan[:-1], "show version"]):
        with pytest.raises(CommandNotAllowedError):
            _run(_executor(runner=other), _token(commands))
    assert other.calls == []


def test_a_device_that_is_no_longer_the_same_is_refused() -> None:
    other = ResolvedDevice("nb1", "dev-OTHER", "LAB", "10.9.9.9", None, None)
    other_source = ResolvedDevice("nb2", "dev-1", "LAB", "10.1.2.3", None, None)
    runner = FakeRunner()

    for changed in (other, other_source):
        with pytest.raises(ex.DeviceChangedError):
            _run(_executor(FakeResolver(changed), runner))

    assert runner.calls == []


def test_resolution_errors_pass_through_and_nothing_runs() -> None:
    runner = FakeRunner()

    with pytest.raises(DeviceNotFoundError):
        _run(_executor(FakeResolver(error=DeviceNotFoundError()), runner))

    assert runner.calls == []


def test_without_the_exact_secret_values_nothing_runs() -> None:
    runner = FakeRunner()

    with pytest.raises(ex.SecretsUnavailableError):
        _run(_executor(runner=runner, secrets=None))

    assert runner.calls == []


def test_the_executor_resolves_the_name_from_the_token_not_from_the_caller() -> None:
    resolver = FakeResolver()

    _run(_executor(resolver))

    assert resolver.names == ["LAB"]


# -- failures, limits, audit ------------------------------------------------------------------


def test_a_failed_command_is_reported_with_a_redacted_error_and_no_handle() -> None:
    runner = FakeRunner(DeviceCommandOutput(False, "login failed password=hunter2xx", ()))

    result = _run(_executor(runner=runner, secrets=["hunter2xx"]))

    assert result.success is False
    assert "hunter2xx" not in (result.error or "")
    assert result.error and "login failed" in result.error
    assert result.handle is None


def test_huge_output_is_cut_with_a_marker() -> None:
    big = "x" * (ex.MAX_OUTPUT_CHARS + 5000)
    runner = FakeRunner(DeviceCommandOutput(True, None, (("show running-config", big),)))

    result = _run(_executor(runner=runner))

    assert result.truncated is True
    assert len(result.output) <= ex.MAX_OUTPUT_CHARS + 200
    assert "truncated" in result.output.splitlines()[-1]


def test_small_output_is_not_marked_truncated() -> None:
    assert _run(_executor()).truncated is False


def test_the_audit_line_has_ids_and_hashes_but_no_content(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="ai_assistant.audit"):
        result = _run(_executor())

    line = "\n".join(r.getMessage() for r in caplog.records)
    assert f"user_id={USER}" in line
    assert "device_id=dev-1" in line
    assert "outcome=ok" in line
    assert result.handle in line
    assert "hostname LAB" not in line and "show running-config" not in line


def test_the_name_to_resolve_is_the_signed_one() -> None:
    resolver = FakeResolver()

    _run(_executor(resolver), _token(device_name="edge-1"))

    assert resolver.names == ["edge-1"]


def test_a_secret_the_patterns_cannot_see_is_still_scrubbed_by_its_exact_value() -> None:
    runner = FakeRunner(
        DeviceCommandOutput(True, None, (("show running-config", "banner bareSecretValue99\n"),))
    )

    result = _run(_executor(runner=runner, secrets=["bareSecretValue99"]))

    assert "bareSecretValue99" not in result.output
    assert "banner" in result.output
    # and without the exact value registered, nothing hides it: the test above is not vacuous
    plain = _run(_executor(runner=runner, secrets=[]))
    assert "bareSecretValue99" in plain.output


def test_only_a_successful_run_with_output_gets_a_handle() -> None:
    partial = FakeRunner(
        DeviceCommandOutput(False, "timeout", (("show running-config", "half the config"),))
    )
    empty = FakeRunner(DeviceCommandOutput(True, None, ()))

    assert _run(_executor(runner=partial)).handle is None
    assert _run(_executor(runner=empty)).handle is None
    assert _run(_executor(runner=partial)).output  # partial output is still shown


def test_the_audit_line_says_whether_the_run_failed(caplog) -> None:
    runner = FakeRunner(DeviceCommandOutput(False, "timeout", ()))

    with caplog.at_level(logging.INFO, logger="ai_assistant.audit"):
        _run(_executor(runner=runner))

    assert "outcome=failed" in "\n".join(r.getMessage() for r in caplog.records)


def test_output_too_large_for_a_handle_is_returned_without_one() -> None:
    class TooBig(ResultStore):
        async def put(self, user_id, result):
            raise ValueError("result is too large to store")

    result = _run(_executor(store=TooBig(InMemoryResultBackend())))

    assert result.handle is None and "hostname LAB" in result.output


def test_a_long_error_is_cut() -> None:
    runner = FakeRunner(DeviceCommandOutput(False, "e" * 5000, ()))

    assert len(_run(_executor(runner=runner)).error or "") <= ex.MAX_ERROR_CHARS


def test_the_users_driver_choice_is_passed_to_the_runner() -> None:
    unknown = ResolvedDevice("nb1", "dev-1", "LAB", "10.1.2.3", None, None)
    runner = FakeRunner()

    _run(_executor(FakeResolver(unknown), runner), network_driver="cisco_xe")

    assert runner.drivers == ["cisco_xe"]
    assert runner.calls[0][0] == unknown  # the resolved device itself is untouched


def test_without_a_choice_the_runner_gets_none() -> None:
    runner = FakeRunner()

    _run(_executor(runner=runner))

    assert runner.drivers == [None]


def test_an_unknown_driver_name_is_refused_before_anything_runs() -> None:
    runner = FakeRunner()

    with pytest.raises(ex.InvalidConfirmationError):
        _run(_executor(runner=runner), network_driver="rm -rf")

    assert runner.calls == []


def test_an_address_that_changed_since_the_card_was_shown_is_refused() -> None:
    moved = ResolvedDevice("nb1", "dev-1", "LAB", "10.9.9.9", "cisco_ios", "cisco_ios")
    runner = FakeRunner()

    with pytest.raises(ex.DeviceChangedError):
        _run(_executor(FakeResolver(moved), runner))

    assert runner.calls == []


def test_the_choice_of_driver_is_ignored_when_the_inventory_already_knows_one() -> None:
    runner = FakeRunner()

    _run(_executor(runner=runner), network_driver="juniper_junos")

    assert runner.drivers == [None]  # DEVICE has cisco_ios: the inventory value stands


def test_the_choice_of_driver_is_used_when_the_inventory_names_none() -> None:
    unknown = ResolvedDevice("nb1", "dev-1", "LAB", "10.1.2.3", None, None)
    runner = FakeRunner()

    _run(_executor(FakeResolver(unknown), runner), network_driver="cisco_xe")

    assert runner.drivers == ["cisco_xe"]


# -- wall-clock cap and concurrency cap (review 2026-11-01) -----------------------------------


class SlowRunner(FakeRunner):
    def __init__(self, release: asyncio.Event | None = None, delay: float = 0.0) -> None:
        super().__init__()
        self.release, self.delay, self.started = release, delay, 0

    async def run(self, device, commands, **kwargs):
        self.started += 1
        if self.release is not None:
            await self.release.wait()
        if self.delay:
            await asyncio.sleep(self.delay)
        return await super().run(device, commands, **kwargs)


def test_a_run_that_does_not_finish_in_time_is_reported_and_stores_nothing(monkeypatch) -> None:
    monkeypatch.setattr(ex, "RUN_TIMEOUT_SECONDS", 0.05)
    # ``show running-config`` is a long-read command: its floor is lowered too, or it would win.
    monkeypatch.setattr(ex, "LONG_READ_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(ex, "CONNECT_SLACK_SECONDS", 0)

    result = _run(_executor(runner=SlowRunner(delay=2)))

    assert result.success is False
    assert "did not finish" in (result.error or "")
    assert result.handle is None and result.output == ""


def test_a_run_inside_the_time_limit_is_unaffected(monkeypatch) -> None:
    monkeypatch.setattr(ex, "RUN_TIMEOUT_SECONDS", 5)

    assert _run(_executor(runner=SlowRunner(delay=0.01))).success is True


def test_a_user_may_have_only_two_runs_open_at_once_and_the_counter_resets() -> None:
    async def scenario():
        release = asyncio.Event()
        runner = SlowRunner(release=release)
        executor = _executor(runner=runner)
        token = _token()
        first = asyncio.create_task(executor.execute(user_id=USER, token=token, credential_id=1))
        second = asyncio.create_task(executor.execute(user_id=USER, token=token, credential_id=1))
        await asyncio.sleep(0.05)
        with pytest.raises(ex.TooManyRunsError):
            await executor.execute(user_id=USER, token=token, credential_id=1)
        other_user = asyncio.create_task(
            executor.execute(user_id=8, token=_token(user_id=8), credential_id=1)
        )
        await asyncio.sleep(0.05)
        release.set()
        results = await asyncio.gather(first, second, other_user)
        started = runner.started
        again = await executor.execute(user_id=USER, token=token, credential_id=1)
        return started, results, again

    started, results, again = asyncio.run(scenario())

    assert started == 3  # the refused third run never reached the device
    assert all(r.success for r in results) and again.success


def test_a_failing_run_gives_its_slot_back() -> None:
    async def scenario():
        runner = FakeRunner()
        executor = _executor(FakeResolver(error=DeviceNotFoundError()), runner)
        for _ in range(ex.MAX_RUNS_PER_USER + 2):
            with pytest.raises(DeviceNotFoundError):
                await executor.execute(user_id=USER, token=_token(), credential_id=1)

    asyncio.run(scenario())  # never TooManyRunsError: the slot is released on every exit


# -- redaction happens before any cut (review 2026-11-01) --------------------------------------


def test_a_secret_that_straddles_the_output_cap_is_redacted_before_the_cut() -> None:
    filler = "x" * (ex.MAX_OUTPUT_CHARS - 20)
    text = f"{filler}\nbanner bareSecretValue99\n" + "y" * 1000
    runner = FakeRunner(DeviceCommandOutput(True, None, (("show running-config", text),)))

    result = _run(_executor(runner=runner, secrets=["bareSecretValue99"]))

    assert "bareS" not in result.output
    assert result.truncated is True


def test_the_cut_falls_on_a_line_boundary_when_there_is_one() -> None:
    lines = "".join(f"line {i:06d}\n" for i in range(ex.MAX_OUTPUT_CHARS // 12 + 500))
    runner = FakeRunner(DeviceCommandOutput(True, None, (("show running-config", lines),)))

    result = _run(_executor(runner=runner))

    body, _, note = result.output.rpartition("\n…[output truncated")
    assert result.truncated is True and note
    assert body.splitlines()[-1].startswith("line ") and len(body.splitlines()[-1]) == 11


def test_an_error_is_redacted_before_it_is_cut() -> None:
    error = "e" * 494 + "hunter2xx" + "z" * 100
    runner = FakeRunner(DeviceCommandOutput(False, error, ()))

    result = _run(_executor(runner=runner, secrets=["hunter2xx"]))

    assert "hunt" not in (result.error or "")
    assert len(result.error or "") <= ex.MAX_ERROR_CHARS


def test_output_beyond_the_raw_limit_is_cut_on_a_line_and_marked() -> None:
    lines = "".join(f"line {i:07d}\n" for i in range(ex.MAX_RAW_CHARS // 13 * 2))
    runner = FakeRunner(DeviceCommandOutput(True, None, (("show running-config", lines),)))

    result = _run(_executor(runner=runner))

    assert result.truncated is True
    assert len(result.output) <= ex.MAX_OUTPUT_CHARS + 200


def test_an_enormous_error_does_not_blow_the_redaction_budget() -> None:
    runner = FakeRunner(DeviceCommandOutput(False, "e" * 3_000_000, ()))

    result = _run(_executor(runner=runner))

    assert result.success is False and len(result.error or "") == ex.MAX_ERROR_CHARS


def test_a_cut_prefers_a_line_boundary_only_when_one_is_near_the_end() -> None:
    assert ex._cut("ab\n" + "x" * 100, 50) == ("ab\n" + "x" * 100)[:50]  # early newline: hard cut
    assert ex._cut("x" * 40 + "\n" + "y" * 100, 50) == "x" * 40
    assert ex._cut("short", 50) == "short"


def test_the_truncation_note_reports_shown_and_total_sizes() -> None:
    import re

    lines = "".join(f"line {i:06d}\n" for i in range(ex.MAX_OUTPUT_CHARS // 12 + 500))
    runner = FakeRunner(DeviceCommandOutput(True, None, (("show running-config", lines),)))

    result = _run(_executor(runner=runner))

    body, _, note = result.output.rpartition("\n…[output truncated")
    shown, total = map(int, re.search(r"showed (\d+) of (\d+)", note).groups())  # type: ignore[union-attr]
    assert shown == len(body) and total > shown


# -- parsing the output (doc/AI_TOOL_CHAIN.md §43) ---------------------------------------------

SHOW_VERSION_TEXT = (
    "Cisco IOS Software, Version 15.2(4)M\nrouter1 uptime is 1 day\nenable password hunter2xx\n"
)


class RecordingGenie:
    def __init__(self, error=None) -> None:
        self.calls, self.error = [], error

    async def parse(self, os_name, outputs):
        from services.ai_assistant.output_parser import ParsedCommand

        self.calls.append((os_name, list(outputs)))
        if self.error:
            raise self.error
        return [ParsedCommand(c, {"os": os_name}, None) for c, _ in outputs]


def _parsing_executor(store, genie=None, secrets=("hunter2xx",)):
    runner = FakeRunner(DeviceCommandOutput(True, None, (("show version", SHOW_VERSION_TEXT),)))
    return ex.DeviceCommandExecutor(
        FakeResolver(),
        runner,
        store,
        secret_loader=lambda user_id: list(secrets),
        genie_factory=lambda user_id: genie,
    )


def test_without_a_parser_nothing_is_parsed() -> None:
    result = _run(_executor())

    assert result.parser == "none"
    assert result.parsed_handle is None
    assert result.parsed_text == ""
    assert result.parse_errors == ()


def test_textfsm_parses_the_redacted_output_and_stores_the_rows() -> None:
    store = ResultStore(InMemoryResultBackend())

    result = _run(_parsing_executor(store), _token(["show version"], parser="textfsm"))

    assert result.parser == "textfsm"
    assert result.parse_errors == ()
    assert result.parsed_handle is not None
    stored = asyncio.run(store.get(USER, result.parsed_handle))
    assert stored is not None and stored.rows is not None
    assert stored.kind == "parsed_output"
    assert stored.data_class is DataClass.CONTENT
    assert stored.rows[0]["hostname"] == "router1"
    assert "router1" in result.parsed_text
    assert "hunter2xx" not in result.parsed_text


def test_the_raw_handle_remembers_what_a_later_parse_needs() -> None:
    store = ResultStore(InMemoryResultBackend())

    result = _run(_parsing_executor(store), _token(["show version"], parser="textfsm"))

    raw = asyncio.run(store.get(USER, result.handle))
    assert raw is not None and raw.meta is not None
    assert raw.meta["commands"] == ["show version"]
    assert raw.meta["parser"] == "textfsm"  # the parser the user confirmed on the card
    assert raw.meta["network_driver"] == "cisco_ios"
    assert raw.meta["platform"] == "cisco_ios"
    # which device it came from, so a later comparison uses that device and not a model's guess
    assert raw.meta["device_name"] == "LAB"
    # the name is only a label; the inventory identity is what two readings are matched on
    assert (raw.meta["source_id"], raw.meta["device_id"]) == ("nb1", "dev-1")
    [[start, end]] = raw.meta["spans"]
    assert raw.text[start:end].startswith("Cisco IOS Software")
    assert "hunter2xx" not in raw.text[start:end]  # the offsets are into the redacted text


def test_spans_stay_exact_when_redaction_changes_the_lengths() -> None:
    runner = FakeRunner(
        DeviceCommandOutput(
            True,
            None,
            (
                ("show a", "enable password hunter2xx\nafter"),
                ("show b", "second output"),
            ),
        )
    )
    store = ResultStore(InMemoryResultBackend())
    executor = ex.DeviceCommandExecutor(
        FakeResolver(), runner, store, secret_loader=lambda user_id: ["hunter2xx"]
    )

    result = _run(executor, _token(["show a", "show b"]))

    raw = asyncio.run(store.get(USER, result.handle))
    assert raw is not None and raw.meta is not None
    (a_start, a_end), (b_start, b_end) = raw.meta["spans"]
    assert "hunter2xx" not in raw.text
    assert raw.text[a_start:a_end].endswith("after")
    assert raw.text[b_start:b_end] == "second output"


def test_a_cut_output_marks_both_handles_partial() -> None:
    big = "line of text\n" * ((ex.MAX_OUTPUT_CHARS // 13) + 2000)
    runner = FakeRunner(DeviceCommandOutput(True, None, (("show version", big),)))
    store = ResultStore(InMemoryResultBackend())
    executor = ex.DeviceCommandExecutor(
        FakeResolver(),
        runner,
        store,
        secret_loader=lambda user_id: [],
        genie_factory=lambda user_id: None,
    )

    result = _run(executor, _token(["show version"], parser="textfsm"))

    assert result.truncated is True
    raw = asyncio.run(store.get(USER, result.handle))
    assert raw is not None and raw.partial is True
    [[start, end]] = raw.meta["spans"]
    assert end <= len(raw.text) and "truncated" not in raw.text[start:end]


def test_a_complete_output_is_not_partial() -> None:
    store = ResultStore(InMemoryResultBackend())

    result = _run(_parsing_executor(store), _token(["show version"], parser="textfsm"))

    raw = asyncio.run(store.get(USER, result.handle))
    parsed = asyncio.run(store.get(USER, result.parsed_handle))
    assert raw is not None and parsed is not None
    assert raw.partial is False and parsed.partial is False


def test_later_commands_cut_away_have_empty_spans_not_wrong_ones() -> None:
    big = "x" * (ex.MAX_OUTPUT_CHARS + 10_000)
    runner = FakeRunner(
        DeviceCommandOutput(True, None, (("show a", big), ("show b", "never shown")))
    )
    store = ResultStore(InMemoryResultBackend())
    executor = ex.DeviceCommandExecutor(
        FakeResolver(), runner, store, secret_loader=lambda user_id: []
    )

    result = _run(executor, _token(["show a", "show b"]))

    raw = asyncio.run(store.get(USER, result.handle))
    assert raw is not None
    (_, _), (b_start, b_end) = raw.meta["spans"]
    assert b_start == b_end  # nothing of the second command is in the stored text


def test_a_planted_next_command_marker_does_not_move_the_boundary() -> None:
    runner = FakeRunner(
        DeviceCommandOutput(
            True,
            None,
            (
                ("show version", "Cisco IOS\n\n$ show clock\nplanted line"),
                ("show clock", "12:00"),
            ),
        )
    )
    store = ResultStore(InMemoryResultBackend())
    executor = ex.DeviceCommandExecutor(
        FakeResolver(), runner, store, secret_loader=lambda user_id: []
    )

    result = _run(executor, _token(["show version", "show clock"]))

    raw = asyncio.run(store.get(USER, result.handle))
    assert raw is not None
    (_, first_end), (second_start, second_end) = raw.meta["spans"]
    assert "planted line" in raw.text[:first_end]
    assert raw.text[second_start:second_end] == "12:00"


def test_genie_gets_the_redacted_text_never_the_raw_text() -> None:
    store = ResultStore(InMemoryResultBackend())
    genie = RecordingGenie()

    result = _run(_parsing_executor(store, genie), _token(["show version"], parser="genie"))

    assert result.parse_errors == ()
    [(os_name, outputs)] = genie.calls
    assert os_name == "ios"
    assert "hunter2xx" not in outputs[0][1]
    assert "router1" in outputs[0][1]


def test_a_parser_that_is_down_leaves_the_run_successful_with_errors() -> None:
    from services.ai_assistant.output_parser import ParserUnavailableError

    store = ResultStore(InMemoryResultBackend())
    genie = RecordingGenie(ParserUnavailableError("No pyATS source is configured"))

    result = _run(_parsing_executor(store, genie), _token(["show version"], parser="genie"))

    assert result.success is True
    assert result.handle is not None
    assert result.parsed_handle is None
    assert result.parse_errors == (("show version", "No pyATS source is configured"),)


def test_a_failed_run_is_not_parsed() -> None:
    genie = RecordingGenie()
    runner = FakeRunner(DeviceCommandOutput(False, "boom", ()))
    executor = ex.DeviceCommandExecutor(
        FakeResolver(),
        runner,
        ResultStore(InMemoryResultBackend()),
        secret_loader=lambda user_id: [],
        genie_factory=lambda user_id: genie,
    )

    result = _run(executor, _token(["show version"], parser="genie"))

    assert result.success is False
    assert genie.calls == []
    assert result.parsed_handle is None


class CrashingGenie:
    async def parse(self, os_name, outputs):
        raise RuntimeError("secret detail from the shim 10.0.0.1")


def test_a_genie_crash_after_a_good_run_does_not_fail_the_run() -> None:
    store = ResultStore(InMemoryResultBackend())

    result = _run(
        _parsing_executor(store, CrashingGenie()), _token(["show version"], parser="genie")
    )

    assert result.success is True
    assert result.handle is not None and result.parsed_handle is None
    assert result.parse_errors == (("show version", "The parser failed on this output"),)
    assert "10.0.0.1" not in result.parsed_text


def test_a_genie_factory_that_crashes_does_not_fail_the_run() -> None:
    runner = FakeRunner(DeviceCommandOutput(True, None, (("show version", SHOW_VERSION_TEXT),)))

    def broken(user_id):
        raise RuntimeError("no database")

    executor = ex.DeviceCommandExecutor(
        FakeResolver(),
        runner,
        ResultStore(InMemoryResultBackend()),
        secret_loader=lambda user_id: [],
        genie_factory=broken,
    )

    result = _run(executor, _token(["show version"], parser="genie"))

    assert result.success is True and result.handle is not None
