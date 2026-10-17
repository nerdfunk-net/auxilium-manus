"""redact_ise_secrets: ERS payload shapes."""

from __future__ import annotations

from services.ise.redaction import REDACTED, redact_ise_secrets


def test_redacts_tacacs_and_radius_shared_secrets() -> None:
    payload = {
        "NetworkDevice": {
            "id": "d1",
            "name": "sw1",
            "tacacsSettings": {"sharedSecret": "tacacs-key", "connectModeOptions": "OFF"},
            "authenticationSettings": {
                "networkProtocol": "RADIUS",
                "radiusSharedSecret": "radius-key",
                "enableKeyWrap": False,
            },
            "snmpsettings": {"version": "TWO_C", "roCommunity": "public"},
        }
    }

    result = redact_ise_secrets(payload)["NetworkDevice"]

    assert result["tacacsSettings"] == {"sharedSecret": REDACTED, "connectModeOptions": "OFF"}
    assert result["authenticationSettings"]["radiusSharedSecret"] == REDACTED
    assert result["authenticationSettings"]["enableKeyWrap"] is False
    assert result["snmpsettings"] == {"version": "TWO_C", "roCommunity": REDACTED}
    assert result["name"] == "sw1"


def test_empty_secret_stays_empty() -> None:
    assert redact_ise_secrets({"tacacsSettings": {"sharedSecret": ""}}) == {
        "tacacsSettings": {"sharedSecret": ""}
    }


def test_redacts_old_and_new_value_of_a_changed_secret_field() -> None:
    payload = {
        "UpdatedFieldsList": {
            "updatedField": [
                {"field": "tacacsSettings.sharedSecret", "oldValue": "old", "newValue": "new"},
                {"field": "description", "oldValue": "a", "newValue": "b"},
            ]
        }
    }

    fields = redact_ise_secrets(payload)["UpdatedFieldsList"]["updatedField"]

    assert fields[0] == {
        "field": "tacacsSettings.sharedSecret",
        "oldValue": REDACTED,
        "newValue": REDACTED,
    }
    assert fields[1] == {"field": "description", "oldValue": "a", "newValue": "b"}


def test_does_not_mutate_its_input() -> None:
    payload = {"tacacsSettings": {"sharedSecret": "k"}}
    redact_ise_secrets(payload)
    assert payload["tacacsSettings"]["sharedSecret"] == "k"


def test_lists_and_scalars_pass_through() -> None:
    assert redact_ise_secrets([{"password": "p"}, 3, "x", None]) == [
        {"password": REDACTED},
        3,
        "x",
        None,
    ]
