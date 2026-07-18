#!/usr/bin/env python3
"""Manual smoke test for the Cisco ISE REST API integration.

Exercises the manus backend's own HTTP API (not the ISE ERS API directly) to
prove the end-to-end path works: log in to manus, register (or reuse) a
Cisco ISE source, then create-or-update a network device with a TACACS
shared secret.

By default it targets the ISE sandbox at ``https://10.10.20.77`` with
``admin`` / ``C1sco12345!`` and creates/updates a device named ``test-001``:

    description   = "testdevice"
    IP address    = 10.10.10.1/32
    Location      = All Locations
    Device Type   = All Device Types
    IPSec device  = No
    TACACS secret = "tacacskey12345"

Usage (from ``backend/``, with the project venv active and the backend
running, e.g. via ``python start.py``)::

    ../.venv/bin/python scripts/ise_test.py

Run with ``--help`` for all options (backend URL/credentials, ISE
URL/credentials, source ID, device name/IP/description/tacacs secret).
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

DEFAULT_BACKEND_URL = "http://localhost:8001"
DEFAULT_BACKEND_USERNAME = "admin"
DEFAULT_BACKEND_PASSWORD = "admin"

DEFAULT_ISE_URL = "https://10.10.20.77"
DEFAULT_ISE_USERNAME = "admin"
DEFAULT_ISE_PASSWORD = "C1sco12345!"  # noqa: S105 — public ISE sandbox credential, not a real secret

DEFAULT_SOURCE_ID = "ise-test"
DEFAULT_DEVICE_NAME = "test-001"
DEFAULT_DEVICE_DESCRIPTION = "testdevice"
DEFAULT_DEVICE_IP = "10.10.10.1"
DEFAULT_DEVICE_MASK = 32
DEFAULT_TACACS_SECRET = "tacacskey12345"  # noqa: S105 — sandbox test value from the CLI, not a real secret

NETWORK_DEVICE_GROUP_LIST = [
    "Location#All Locations",
    "IPSEC#Is IPSEC Device#No",
    "Device Type#All Device Types",
]


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


def ensure_ise_source(
    client: httpx.Client,
    backend_url: str,
    headers: dict[str, str],
    *,
    source_id: str,
    ise_url: str,
    ise_username: str,
    ise_password: str,
) -> None:
    _step(f"Ensure ISE source '{source_id}' is configured")
    response = client.get(f"{backend_url}/api/sources/ise/{source_id}", headers=headers)

    payload = {
        "url": ise_url,
        "username": ise_username,
        "password": ise_password,
        "verify_ssl": False,
        "timeout": 30,
    }

    if response.status_code == 404:
        create_response = client.post(
            f"{backend_url}/api/sources/ise",
            headers=headers,
            json={"source_id": source_id, **payload},
        )
        if create_response.status_code != 201:
            _fail(
                f"failed to create ISE source: "
                f"{create_response.status_code} {create_response.text}"
            )
        print(f"Created ISE source '{source_id}' -> {ise_url}")
    elif response.status_code == 200:
        update_response = client.put(
            f"{backend_url}/api/sources/ise/{source_id}",
            headers=headers,
            json=payload,
        )
        if update_response.status_code != 200:
            _fail(
                f"failed to update ISE source: "
                f"{update_response.status_code} {update_response.text}"
            )
        print(f"Updated existing ISE source '{source_id}' -> {ise_url}")
    else:
        _fail(f"failed to look up ISE source: {response.status_code} {response.text}")


def test_connection(
    client: httpx.Client, backend_url: str, headers: dict[str, str], source_id: str
) -> None:
    _step(f"Test connection for ISE source '{source_id}'")
    response = client.post(
        f"{backend_url}/api/sources/ise/{source_id}/test-connection", headers=headers
    )
    if response.status_code != 200:
        _fail(f"test-connection request failed: {response.status_code} {response.text}")
    result = response.json()
    if not result.get("success"):
        _fail(f"ISE connection test reported failure: {result.get('message')}")
    print(f"Connection OK: {result.get('message')}")


def create_or_update_device(
    client: httpx.Client,
    backend_url: str,
    headers: dict[str, str],
    source_id: str,
    *,
    name: str,
    description: str,
    ip_address: str,
    mask: int,
    tacacs_secret: str,
) -> dict:
    _step(f"Create or update device '{name}'")

    device_payload = {
        "name": name,
        "description": description,
        "NetworkDeviceIPList": [{"ipaddress": ip_address, "mask": mask}],
        "NetworkDeviceGroupList": NETWORK_DEVICE_GROUP_LIST,
        "tacacsSettings": {"sharedSecret": tacacs_secret, "connectModeOptions": "OFF"},
    }

    lookup = client.get(
        f"{backend_url}/api/sources/ise/{source_id}/devices/name/{name}", headers=headers
    )

    if lookup.status_code == 404:
        create_response = client.post(
            f"{backend_url}/api/sources/ise/{source_id}/devices",
            headers=headers,
            json=device_payload,
        )
        if create_response.status_code != 201:
            _fail(f"failed to create device: {create_response.status_code} {create_response.text}")
        device_id = create_response.json()["id"]
        print(f"Created device '{name}' (id={device_id})")
    elif lookup.status_code == 200:
        device_id = lookup.json()["NetworkDevice"]["id"]
        update_response = client.put(
            f"{backend_url}/api/sources/ise/{source_id}/devices/{device_id}",
            headers=headers,
            json=device_payload,
        )
        if update_response.status_code != 200:
            _fail(f"failed to update device: {update_response.status_code} {update_response.text}")
        print(f"Updated existing device '{name}' (id={device_id})")
    else:
        _fail(f"failed to look up device by name: {lookup.status_code} {lookup.text}")

    verify_response = client.get(
        f"{backend_url}/api/sources/ise/{source_id}/devices/{device_id}", headers=headers
    )
    if verify_response.status_code != 200:
        _fail(f"failed to re-fetch device: {verify_response.status_code} {verify_response.text}")
    return verify_response.json()


def list_devices(
    client: httpx.Client, backend_url: str, headers: dict[str, str], source_id: str
) -> None:
    _step(f"List all devices for ISE source '{source_id}'")
    response = client.get(f"{backend_url}/api/sources/ise/{source_id}/devices", headers=headers)
    if response.status_code != 200:
        _fail(f"failed to list devices: {response.status_code} {response.text}")
    result = response.json()
    print(f"Total devices in ISE: {result['total']}")
    for device in result["resources"]:
        print(f"  - {device['name']} (id={device['id']}) — {device.get('description', '')}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument("--backend-username", default=DEFAULT_BACKEND_USERNAME)
    parser.add_argument("--backend-password", default=DEFAULT_BACKEND_PASSWORD)
    parser.add_argument("--ise-url", default=DEFAULT_ISE_URL)
    parser.add_argument("--ise-username", default=DEFAULT_ISE_USERNAME)
    parser.add_argument("--ise-password", default=DEFAULT_ISE_PASSWORD)
    parser.add_argument("--source-id", default=DEFAULT_SOURCE_ID)
    parser.add_argument("--device-name", default=DEFAULT_DEVICE_NAME)
    parser.add_argument("--device-description", default=DEFAULT_DEVICE_DESCRIPTION)
    parser.add_argument("--device-ip", default=DEFAULT_DEVICE_IP)
    parser.add_argument("--device-mask", type=int, default=DEFAULT_DEVICE_MASK)
    parser.add_argument("--tacacs-secret", default=DEFAULT_TACACS_SECRET)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    with httpx.Client(timeout=30.0) as client:
        token = login(client, args.backend_url, args.backend_username, args.backend_password)
        headers = {"Authorization": f"Bearer {token}"}

        ensure_ise_source(
            client,
            args.backend_url,
            headers,
            source_id=args.source_id,
            ise_url=args.ise_url,
            ise_username=args.ise_username,
            ise_password=args.ise_password,
        )

        test_connection(client, args.backend_url, headers, args.source_id)

        device = create_or_update_device(
            client,
            args.backend_url,
            headers,
            args.source_id,
            name=args.device_name,
            description=args.device_description,
            ip_address=args.device_ip,
            mask=args.device_mask,
            tacacs_secret=args.tacacs_secret,
        )

        _step(f"Final state of device '{args.device_name}'")
        print(json.dumps(device, indent=2))

        list_devices(client, args.backend_url, headers, args.source_id)

    print("\nSUCCESS: Cisco ISE REST API integration is working.")


if __name__ == "__main__":
    main()
