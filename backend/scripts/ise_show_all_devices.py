#!/usr/bin/env python3
"""Manual test: list every network device in Cisco ISE with full detail.

Exercises the manus backend's own HTTP API (not the ISE ERS API directly),
the same pattern as ``ise_test.py``: log in to manus, ensure (or reuse) a
Cisco ISE source, then list every device and print each one's full detail
(``NetworkDeviceIPList``, ``NetworkDeviceGroupList``, ``tacacsSettings``) so
the shape of non-standard entries can be inspected directly — in particular
an ISE IP *range* such as ``"192.168.178.1-254"``, which Cisco ISE stores as
a literal string in ``ipaddress`` (with ``mask`` as an unrelated filler
value, typically ``32``) rather than a clean CIDR network address.

By default it targets the ISE sandbox at ``https://10.10.20.77`` with
``admin`` / ``C1sco12345!``.

Usage (from ``backend/``, with the project venv active and the backend
running, e.g. via ``python start.py``)::

    ../.venv/bin/python scripts/ise_show_all_devices.py

Run with ``--help`` for all options (backend URL/credentials, ISE
URL/credentials, source ID).
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
PAGE_SIZE = 100


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


def list_all_device_summaries(
    client: httpx.Client, backend_url: str, headers: dict[str, str], source_id: str
) -> list[dict]:
    _step(f"List all device summaries for ISE source '{source_id}'")
    summaries: list[dict] = []
    page = 1
    while True:
        response = client.get(
            f"{backend_url}/api/sources/ise/{source_id}/devices",
            headers=headers,
            params={"page": page, "size": PAGE_SIZE},
        )
        if response.status_code != 200:
            _fail(f"failed to list devices: {response.status_code} {response.text}")
        result = response.json()
        summaries.extend(result["resources"])
        if not result.get("next_page"):
            break
        page += 1
    print(f"Total devices in ISE: {len(summaries)}")
    return summaries


def show_device_detail(
    client: httpx.Client,
    backend_url: str,
    headers: dict[str, str],
    source_id: str,
    device_id: str,
) -> dict:
    response = client.get(
        f"{backend_url}/api/sources/ise/{source_id}/devices/{device_id}", headers=headers
    )
    if response.status_code != 200:
        _fail(f"failed to fetch device '{device_id}': {response.status_code} {response.text}")
    return response.json()


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

        summaries = list_all_device_summaries(client, args.backend_url, headers, args.source_id)

        _step("Full detail for every device")
        for summary in summaries:
            detail = show_device_detail(
                client, args.backend_url, headers, args.source_id, summary["id"]
            )
            print(f"\n--- {summary['name']} (id={summary['id']}) ---")
            print(json.dumps(detail, indent=2))

    print("\nSUCCESS: listed all Cisco ISE network devices.")


if __name__ == "__main__":
    main()
