"""encrypt-attribute / decrypt-attribute: what one device's failure does to the others (P-C).

Both run on ``run_per_device``: any problem of one device's data fails that device only and a
later device still runs; a destination that can never be written stays a step-wide config error.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from core.passphrase_cipher import encrypt_with_passphrase
from tests.unit._step_helpers import (
    call_step,
    make_context,
    make_device,
    make_run,
    patch_object_session,
)
from workflow_steps.decrypt_attribute import executor as decrypt_mod
from workflow_steps.encrypt_attribute import executor as encrypt_mod

_PASS = "shared-secret-passphrase"
_CRED = ("aes-256-gcm", _PASS)

ENC_CONFIG = {
    "source_path": "run_input.pw",
    "destination_path": "secrets.pw_enc",
    "credential_reference": "vault",
}
DEC_CONFIG = {
    "source_path": "nautobot.pw_enc",
    "destination_path": "secrets.pw",
    "credential_reference": "vault",
}


def _enc_ctx(**bags_by_device: Any) -> Any:
    return make_context(
        [
            make_device(name, attribute_bags={"run_input": {"pw": value}})
            for name, value in bags_by_device.items()
        ]
    )


async def _run(mod: Any, config: dict[str, Any], context: Any) -> Any:
    with (
        patch_object_session(mod.__name__),
        patch.object(mod, "resolve_shared_secret_credential", return_value=_CRED),
    ):
        return await call_step(mod.execute, config, context, run=make_run())


def _by_name(outcomes: Any) -> dict[str, Any]:
    return {o.name: o.context.devices for o in outcomes}


@pytest.mark.asyncio
async def test_encrypt_unexpected_error_fails_that_device_only_and_hides_its_text() -> None:
    calls = 0
    real = encrypt_with_passphrase

    def flaky(value: str, passphrase: str, **kwargs: Any) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("kdf backend said pw=hunter2-secret")
        return real(value, passphrase, **kwargs)

    with patch.object(encrypt_mod, "encrypt_with_passphrase", flaky):
        outcomes = await _run(encrypt_mod, ENC_CONFIG, _enc_ctx(a="one", b="two"))

    by = _by_name(outcomes)
    assert set(by["success"]) == {"b"} and set(by["failure"]) == {"a"}
    error = by["failure"]["a"].errors[-1]
    assert error.message == "RuntimeError" and "hunter2" not in repr(by["failure"]["a"].errors)
    assert error.failure is not None


@pytest.mark.asyncio
async def test_encrypt_data_dependent_write_error_fails_that_device_only() -> None:
    ctx = make_context(
        [
            make_device(
                "a", attribute_bags={"run_input": {"pw": "one"}, "secrets": {"entries": "scalar"}}
            ),
            make_device("b", attribute_bags={"run_input": {"pw": "two"}}),
        ]
    )
    config = {**ENC_CONFIG, "destination_path": "secrets.entries[name=x].pw_enc"}

    by = _by_name(await _run(encrypt_mod, config, ctx))

    assert set(by["success"]) == {"b"} and set(by["failure"]) == {"a"}


@pytest.mark.asyncio
@pytest.mark.parametrize("module", [encrypt_mod, decrypt_mod])
async def test_a_destination_that_can_never_be_written_is_a_config_error(module: Any) -> None:
    config = {
        **(ENC_CONFIG if module is encrypt_mod else DEC_CONFIG),
        "destination_path": "parsed.x",
    }
    ctx = _enc_ctx(a=None)  # nothing to encrypt: the config error must not depend on data

    with pytest.raises(ValueError, match="parsed|reserved"):
        await _run(module, config, ctx)


@pytest.mark.asyncio
async def test_encrypt_failures_carry_a_failure_record() -> None:
    sealed_ctx = make_context([make_device("a", attribute_bags={"run_input": {"pw": "x"}})])
    config = {**ENC_CONFIG}
    with patch.object(
        encrypt_mod, "encrypt_with_passphrase", side_effect=encrypt_mod.PassphraseCipherError("bad")
    ):
        outcomes = await _run(encrypt_mod, config, sealed_ctx)

    error = _by_name(outcomes)["failure"]["a"].errors[-1]
    assert error.code == "encryption_failed" and error.message == "bad"
    assert error.failure is not None and error.failure.kind == "bad_request"


def _dec_ctx(tokens: dict[str, str]) -> Any:
    return make_context(
        [
            make_device(name, attribute_bags={"nautobot": {"pw_enc": token}})
            for name, token in tokens.items()
        ]
    )


@pytest.mark.asyncio
async def test_decrypt_wrong_token_fails_that_device_and_the_next_still_runs() -> None:
    good = encrypt_with_passphrase("clear", _PASS)

    by = _by_name(await _run(decrypt_mod, DEC_CONFIG, _dec_ctx({"a": "garbage", "b": good})))

    assert set(by["success"]) == {"b"} and set(by["failure"]) == {"a"}
    error = by["failure"]["a"].errors[-1]
    assert error.code == "decryption_failed"
    assert error.failure is not None and error.failure.kind == "bad_request"


@pytest.mark.asyncio
async def test_decrypt_unexpected_error_fails_that_device_only() -> None:
    good = encrypt_with_passphrase("clear", _PASS)
    calls = 0
    real = decrypt_mod.decrypt_with_passphrase

    def flaky(token: str, passphrase: str, **kwargs: Any) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom pw=hunter2-secret")
        return real(token, passphrase, **kwargs)

    with patch.object(decrypt_mod, "decrypt_with_passphrase", flaky):
        outcomes = await _run(decrypt_mod, DEC_CONFIG, _dec_ctx({"a": good, "b": good}))

    by = _by_name(outcomes)
    assert set(by["success"]) == {"b"} and set(by["failure"]) == {"a"}
    assert "hunter2" not in repr(by["failure"]["a"].errors)


@pytest.mark.asyncio
async def test_decrypt_list_mode_not_a_list_has_a_failure_record() -> None:
    config = {**DEC_CONFIG, "item_field": "password", "source_path": "nautobot.pw_enc"}

    by = _by_name(await _run(decrypt_mod, config, _dec_ctx({"a": "not-a-list"})))

    error = by["failure"]["a"].errors[-1]
    assert error.code == "not_a_list" and error.failure is not None


@pytest.mark.asyncio
async def test_decrypt_counts_split_decrypted_and_skipped() -> None:
    good = encrypt_with_passphrase("clear", _PASS)
    ctx = make_context(
        [
            make_device("a", attribute_bags={"nautobot": {"pw_enc": good}}),
            make_device("b"),
        ]
    )

    outcomes = await _run(decrypt_mod, DEC_CONFIG, ctx)

    metadata = outcomes[0].context.metadata
    assert metadata["node-1.decrypted_count"] == 1
    assert metadata["node-1.skipped_count"] == 1
    assert metadata["node-1.failed_count"] == 0
