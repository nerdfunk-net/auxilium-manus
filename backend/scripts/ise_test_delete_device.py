#!/usr/bin/env python3
"""Manual smoke test for deleting a Cisco ISE device.

Companion to ``ise_test.py`` and ``ise_test_update_tacacs.py``. Drives the
manus backend's REST API (not the ISE ERS API directly) to delete an
existing device — by default the ``test-001`` device created by
``ise_test.py`` in the ``ise-test`` source — then confirms it is gone by
re-fetching it (expects 404) and re-listing all devices for the source.

Usage (from ``backend/``, with the project venv active and the backend
running, e.g. via ``python start.py``)::

    ../.venv/bin/python scripts/ise_test_delete_device.py

Run with ``--help`` for all options.
"""

from __future__ import annotations

import argparse
import sys

import httpx

DEFAULT_BACKEND_URL = "http://localhost:8001"
DEFAULT_BACKEND_USERNAME = "admin"
DEFAULT_BACKEND_PASSWORD = "admin"

DEFAULT_SOURCE_ID = "ise-test"
DEFAULT_DEVICE_NAME = "test-001"


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


def get_device_id_by_name(
    client: httpx.Client, backend_url: str, headers: dict[str, str], source_id: str, name: str
) -> str:
    _step(f"Look up device '{name}' in source '{source_id}'")
    response = client.get(
        f"{backend_url}/api/sources/ise/{source_id}/devices/name/{name}", headers=headers
    )
    if response.status_code == 404:
        _fail(f"device '{name}' not found in source '{source_id}' — nothing to delete.")
    if response.status_code != 200:
        _fail(f"failed to look up device by name: {response.status_code} {response.text}")
    device_id = response.json()["NetworkDevice"]["id"]
    print(f"Found device id={device_id}")
    return device_id


def delete_device(
    client: httpx.Client, backend_url: str, headers: dict[str, str], source_id: str, device_id: str
) -> None:
    _step(f"Delete device id={device_id}")
    response = client.delete(
        f"{backend_url}/api/sources/ise/{source_id}/devices/{device_id}", headers=headers
    )
    if response.status_code != 204:
        _fail(f"failed to delete device: {response.status_code} {response.text}")
    print("Delete request accepted (204 No Content).")


def verify_deleted(
    client: httpx.Client,
    backend_url: str,
    headers: dict[str, str],
    source_id: str,
    device_id: str,
    device_name: str,
) -> None:
    _step("Verify the device is gone")
    response = client.get(
        f"{backend_url}/api/sources/ise/{source_id}/devices/{device_id}", headers=headers
    )
    if response.status_code != 404:
        _fail(
            f"device still exists after delete: expected 404, got "
            f"{response.status_code} {response.text}"
        )
    print(f"GET by id now returns 404 — device id={device_id} confirmed deleted.")

    list_response = client.get(
        f"{backend_url}/api/sources/ise/{source_id}/devices", headers=headers
    )
    if list_response.status_code != 200:
        _fail(f"failed to list devices: {list_response.status_code} {list_response.text}")
    result = list_response.json()
    remaining_names = [device["name"] for device in result["resources"]]
    if device_name in remaining_names:
        _fail(f"device '{device_name}' still appears in the device list: {remaining_names}")
    print(f"Total devices remaining in ISE: {result['total']}")
    for device in result["resources"]:
        print(f"  - {device['name']} (id={device['id']}) — {device.get('description', '')}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument("--backend-username", default=DEFAULT_BACKEND_USERNAME)
    parser.add_argument("--backend-password", default=DEFAULT_BACKEND_PASSWORD)
    parser.add_argument("--source-id", default=DEFAULT_SOURCE_ID)
    parser.add_argument("--device-name", default=DEFAULT_DEVICE_NAME)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    with httpx.Client(timeout=30.0) as client:
        token = login(client, args.backend_url, args.backend_username, args.backend_password)
        headers = {"Authorization": f"Bearer {token}"}

        device_id = get_device_id_by_name(
            client, args.backend_url, headers, args.source_id, args.device_name
        )
        delete_device(client, args.backend_url, headers, args.source_id, device_id)
        verify_deleted(
            client, args.backend_url, headers, args.source_id, device_id, args.device_name
        )

    print("\nSUCCESS: Cisco ISE device deletion via the REST API is working.")


if __name__ == "__main__":
    main()
