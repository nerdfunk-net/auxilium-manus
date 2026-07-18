#!/usr/bin/env python3
"""Manual smoke test for updating a Cisco ISE device's TACACS shared secret.

Companion to ``ise_test.py``. Drives the manus backend's REST API (not the
ISE ERS API directly) to update the TACACS shared secret on an existing
device — by default the ``test-001`` device created by ``ise_test.py`` in
the ``ise-test`` source — to ``newTacacsKey``, then re-fetches the device to
confirm the secret changed while everything else (IP, description, device
group list) stayed the same.

Sends only ``tacacsSettings`` in the update request on purpose: the manus
backend does a read-merge-write against Cisco ISE's ERS API, so this also
exercises that merge path (ISE itself would otherwise wipe untouched fields
on a raw ``PUT``).

Usage (from ``backend/``, with the project venv active and the backend
running, e.g. via ``python start.py``)::

    ../.venv/bin/python scripts/ise_test_update_tacacs.py

Run with ``--help`` for all options.
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

DEFAULT_BACKEND_URL = "http://localhost:8001"
DEFAULT_BACKEND_USERNAME = "admin"
DEFAULT_BACKEND_PASSWORD = "admin"

DEFAULT_SOURCE_ID = "ise-test"
DEFAULT_DEVICE_NAME = "test-001"
DEFAULT_NEW_TACACS_SECRET = "newTacacsKey"  # noqa: S105 — sandbox test value, not a real secret


def _step(message: str) -> None:
    print(f"\n=== {message} ===")


def _fail(message: str) -> None:
    print(f"FAILED: {message}", file=sys.stderr)
    sys.exit(1)


def login(client: httpx.Client, backend_url: str, username: str, password: str) -> str:
    _step(f"Log in to manus backend as '{username}'")
    response = client.post(
        f"{backend_url}/api/auth/login",
        json={"username": username, "password": password},
    )
    if response.status_code != 200:
        _fail(f"login failed ({response.status_code}): {response.text}")
    token = response.json()["access_token"]
    print("Logged in, obtained access token.")
    return token


def get_device_by_name(
    client: httpx.Client, backend_url: str, headers: dict[str, str], source_id: str, name: str
) -> dict:
    response = client.get(
        f"{backend_url}/api/sources/ise/{source_id}/devices/name/{name}", headers=headers
    )
    if response.status_code == 404:
        _fail(
            f"device '{name}' not found in source '{source_id}'. "
            "Run ise_test.py first to create it."
        )
    if response.status_code != 200:
        _fail(f"failed to look up device by name: {response.status_code} {response.text}")
    return response.json()


def update_tacacs_secret(
    client: httpx.Client,
    backend_url: str,
    headers: dict[str, str],
    source_id: str,
    device_id: str,
    new_secret: str,
) -> None:
    _step(f"Update TACACS shared secret on device id={device_id}")
    response = client.put(
        f"{backend_url}/api/sources/ise/{source_id}/devices/{device_id}",
        headers=headers,
        json={"tacacsSettings": {"sharedSecret": new_secret, "connectModeOptions": "OFF"}},
    )
    if response.status_code != 200:
        _fail(f"failed to update TACACS secret: {response.status_code} {response.text}")
    print("Update request accepted.")
    print(json.dumps(response.json(), indent=2))


def verify_update(
    client: httpx.Client,
    backend_url: str,
    headers: dict[str, str],
    source_id: str,
    device_id: str,
    *,
    expected_secret: str,
    previous_device: dict,
) -> None:
    _step("Re-fetch device to verify the update")
    response = client.get(
        f"{backend_url}/api/sources/ise/{source_id}/devices/{device_id}", headers=headers
    )
    if response.status_code != 200:
        _fail(f"failed to re-fetch device: {response.status_code} {response.text}")

    device = response.json()["NetworkDevice"]
    print(json.dumps(device, indent=2))

    actual_secret = device.get("tacacsSettings", {}).get("sharedSecret")
    if actual_secret != expected_secret:
        _fail(
            f"TACACS secret was not updated as expected: "
            f"got {actual_secret!r}, wanted {expected_secret!r}"
        )
    print(f"TACACS shared secret is now '{actual_secret}' — update confirmed.")

    previous = previous_device["NetworkDevice"]
    unchanged_fields = ("description", "NetworkDeviceIPList", "NetworkDeviceGroupList")
    for field in unchanged_fields:
        if device.get(field) != previous.get(field):
            _fail(
                f"field '{field}' changed unexpectedly during the TACACS-only update: "
                f"before={previous.get(field)!r} after={device.get(field)!r}"
            )
    print(
        "Description, IP list, and device group list are unchanged — "
        "merge-safe update confirmed."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument("--backend-username", default=DEFAULT_BACKEND_USERNAME)
    parser.add_argument("--backend-password", default=DEFAULT_BACKEND_PASSWORD)
    parser.add_argument("--source-id", default=DEFAULT_SOURCE_ID)
    parser.add_argument("--device-name", default=DEFAULT_DEVICE_NAME)
    parser.add_argument("--new-tacacs-secret", default=DEFAULT_NEW_TACACS_SECRET)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    with httpx.Client(timeout=30.0) as client:
        token = login(client, args.backend_url, args.backend_username, args.backend_password)
        headers = {"Authorization": f"Bearer {token}"}

        _step(f"Look up device '{args.device_name}' in source '{args.source_id}'")
        previous_device = get_device_by_name(
            client, args.backend_url, headers, args.source_id, args.device_name
        )
        device_id = previous_device["NetworkDevice"]["id"]
        previous_secret = previous_device["NetworkDevice"].get("tacacsSettings", {}).get(
            "sharedSecret"
        )
        print(f"Found device id={device_id}, current TACACS secret='{previous_secret}'")

        update_tacacs_secret(
            client, args.backend_url, headers, args.source_id, device_id, args.new_tacacs_secret
        )

        verify_update(
            client,
            args.backend_url,
            headers,
            args.source_id,
            device_id,
            expected_secret=args.new_tacacs_secret,
            previous_device=previous_device,
        )

    print("\nSUCCESS: Cisco ISE TACACS key update via the REST API is working.")


if __name__ == "__main__":
    main()
