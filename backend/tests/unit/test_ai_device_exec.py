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
