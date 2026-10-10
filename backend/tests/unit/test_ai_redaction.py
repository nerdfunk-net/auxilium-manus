"""Redactor: secrets become restorable tokens; Jinja expressions are never touched."""

from __future__ import annotations

import pytest

from services.ai_assistant.redaction import Redactor, SecretRelocationError

CISCO_SAMPLE = """\
hostname lab
enable secret 9 $9$abcDEF123456$verylonghashvalue
username admin privilege 15 secret 5 $1$salt$hashhashhash
username ops password 7 0822455D0A16
tacacs-server host 10.0.0.5 key 7 060506324F41
radius-server key MyRadiusSecret
snmp-server community public RO
snmp-server user bob grp v3 auth sha AuthPassw0rd priv aes 128 PrivPassw0rd
ntp authentication-key 1 md5 NtpKeyValue
 ip ospf message-digest-key 1 md5 OspfKeyValue
line vty 0 4
 password VtyPassword
"""

SECRETS = [
    "$9$abcDEF123456$verylonghashvalue",
    "$1$salt$hashhashhash",
    "0822455D0A16",
    "060506324F41",
    "MyRadiusSecret",
    "public",
    "AuthPassw0rd",
    "PrivPassw0rd",
    "NtpKeyValue",
    "OspfKeyValue",
    "VtyPassword",
]


@pytest.mark.parametrize("secret", SECRETS)
def test_cisco_secrets_are_removed_from_config_text(secret: str) -> None:
    redacted = Redactor().redact(CISCO_SAMPLE)

    assert secret not in redacted


def test_surrounding_config_is_preserved_so_the_model_can_still_reason() -> None:
    redacted = Redactor().redact(CISCO_SAMPLE)

    for kept in ("hostname lab", "enable secret 9", "username admin privilege 15", "line vty 0 4"):
        assert kept in redacted


def test_restore_round_trips_the_original_text_exactly() -> None:
    redactor = Redactor()

    assert redactor.restore(redactor.redact(CISCO_SAMPLE)) == CISCO_SAMPLE


def test_same_secret_gets_the_same_token_and_distinct_secrets_differ() -> None:
    redactor = Redactor()
    out = redactor.redact(
        "enable secret 5 aaa111\nusername x secret 5 aaa111\nenable password bbb222"
    )

    tokens = [word for word in out.split() if word.startswith("__SECRET_")]
    assert tokens[0] == tokens[1] != tokens[2]


def test_private_key_block_is_redacted_whole() -> None:
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEvQIBADANBgkq\nabcdef\n-----END RSA PRIVATE KEY-----"
    redactor = Redactor()
    out = redactor.redact(f"before\n{pem}\nafter")

    assert "MIIEvQIBADANBgkq" not in out
    assert out.startswith("before\n") and out.endswith("\nafter")
    assert redactor.restore(out) == f"before\n{pem}\nafter"


@pytest.mark.parametrize(
    "text",
    [
        "enable secret 9 {{ enable_secret }}",
        "username {{ user }} password {{ pw }}",
        "snmp-server community {{ snmp.community }} RO",
        "password: {{ vault_password }}",
        "{% set password = pw %}",
        "tacacs-server host 10.0.0.5 key {{ tacacs.shared_secret }}",
    ],
)
def test_jinja_expressions_are_never_redacted(text: str) -> None:
    assert Redactor().redact(text) == text


def test_generic_assignments_and_auth_headers() -> None:
    out = Redactor().redact(
        'api_key = "abcd1234efgh"\npassword: hunter2hunter2\n'
        "Authorization: Bearer abc.def.ghi-123456"
    )

    for leaked in ("abcd1234efgh", "hunter2hunter2", "abc.def.ghi-123456"):
        assert leaked not in out


def test_plain_prose_without_values_is_left_alone() -> None:
    text = "Use a strong password policy and rotate the secret regularly."

    assert Redactor().redact(text) == text


def test_redact_data_handles_nested_structures_and_secret_key_names() -> None:
    redactor = Redactor()
    data = {
        "name": "lab",
        "password": "plain-text-pw",
        "nested": [{"note": "enable secret 5 zzz999"}],
    }

    out = redactor.redact_data(data)

    assert out["name"] == "lab"
    assert "plain-text-pw" not in str(out)
    assert "zzz999" not in str(out)
    assert data["password"] == "plain-text-pw"  # input not mutated


def test_restore_leaves_unknown_tokens_untouched() -> None:
    assert Redactor().restore("keep __SECRET_99__ as is") == "keep __SECRET_99__ as is"


def test_placeholder_marker_is_detected() -> None:
    assert Redactor.contains_unresolved_placeholder("x ***REDACTED*** y")
    assert not Redactor.contains_unresolved_placeholder("clean text")


# -- structured tokenisation (workflow configs) ---------------------------------------------


def test_tokenize_data_replaces_secret_named_values_and_sealed_envelopes_restorably() -> None:
    redactor = Redactor()
    sealed = {"__am_sealed__": True, "v": 1, "ct": "gAAAA-ciphertext"}
    data = {
        "name": "lab",
        "password": "plain-text-pw",
        "nested": {"api_key": "abcd1234", "ok": "keep"},
        "bag": {"tacacs": {"shared_secret": sealed}},
        "items": [{"token": "tok-9999"}, "enable secret 5 zzz999"],
        "count": 3,
    }

    tokenised = redactor.tokenize_data(data)
    flat = str(tokenised)

    for leaked in ("plain-text-pw", "abcd1234", "gAAAA-ciphertext", "tok-9999", "zzz999"):
        assert leaked not in flat
    assert tokenised["name"] == "lab" and tokenised["count"] == 3
    assert redactor.restore_data(tokenised) == data
    assert data["password"] == "plain-text-pw"  # input not mutated


def test_restore_data_keeps_unknown_tokens_and_non_secret_values() -> None:
    redactor = Redactor()
    value = {"a": "__SECRET_42__", "b": [1, None, True]}

    assert redactor.restore_data(value) == value


def test_restore_data_refuses_a_token_under_a_different_key() -> None:
    redactor = Redactor()
    tokenised = redactor.tokenize_data(
        {
            "password": "plain-text-pw",
            "cmd": "enable secret 5 zzz999",
            "opts": {"api_key": "k-12345678"},
        }
    )
    password_token, cmd, key_token = (
        tokenised["password"],
        tokenised["cmd"],
        tokenised["opts"]["api_key"],
    )

    assert redactor.restore_data({"password": password_token, "list": []})["password"]
    assert redactor.restore_data({"cmd": cmd})["cmd"] == "enable secret 5 zzz999"
    with pytest.raises(SecretRelocationError):
        redactor.restore_data({"message": password_token})
    with pytest.raises(SecretRelocationError):
        redactor.restore_data({"message": f"see {cmd}"})
    with pytest.raises(SecretRelocationError):
        redactor.restore_data({"items": [{"note": key_token}]})
    # Several fields of one list item keep working under their own key.
    assert redactor.restore_data({"items": [{"api_key": key_token}]}) == {
        "items": [{"api_key": "k-12345678"}]
    }


def test_a_model_supplied_literal_marker_is_detected_anywhere_in_a_structure() -> None:
    assert Redactor.data_contains_placeholder({"a": [{"b": "x ***REDACTED*** y"}]})
    assert not Redactor.data_contains_placeholder({"a": [{"b": "clean"}], "n": 1})
