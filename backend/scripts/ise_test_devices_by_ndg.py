#!/usr/bin/env python3
"""Manual smoke test for listing Cisco ISE devices by network device group.

Companion to ``ise_test.py`` (device CRUD) and the ``ise_test_ndg_*.py``
group scripts. Drives the manus backend's REST API (not the ISE ERS API
directly) to list devices belonging to a given network device group via
``GET /sources/ise/{source_id}/devices/ndg/{group_name}``.

Note: internally this endpoint filters on ISE's ``location`` field, which —
despite its name — matches against ANY entry in a device's
``NetworkDeviceGroupList``, not just ``Location#...`` groups (see
``doc/ISE-REST-API.md``, ISE quirk 8). The default ``--group-name`` below
is a custom, non-Location group used to verify exactly that.

Usage (from ``backend/``, with the project venv active and the backend
running, e.g. via ``python start.py``)::

    ../.venv/bin/python scripts/ise_test_devices_by_ndg.py

    # Any full hierarchical NDG name works, not just custom ones
    ../.venv/bin/python scripts/ise_test_devices_by_ndg.py \\
        --group-name "Location#All Locations"

Run with ``--help`` for all options.
"""

from __future__ import annotations

import argparse
import sys
from urllib.parse import quote

import httpx

DEFAULT_BACKEND_URL = "http://localhost:8001"
DEFAULT_BACKEND_USERNAME = "admin"
DEFAULT_BACKEND_PASSWORD = "admin"
DEFAULT_SOURCE_ID = "ise-test"
DEFAULT_GROUP_NAME = "myGroup#myGroup#my-test-001"


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


def list_devices_by_group(
    client: httpx.Client,
    backend_url: str,
    headers: dict[str, str],
    source_id: str,
    group_name: str,
    *,
    page: int,
    size: int,
) -> None:
    _step(f"List devices in group '{group_name}' for ISE source '{source_id}'")
    response = client.get(
        f"{backend_url}/api/sources/ise/{source_id}/devices/ndg/{quote(group_name, safe='')}",
        headers=headers,
        params={"page": page, "size": size},
    )
    if response.status_code != 200:
        _fail(f"failed to list devices by group: {response.status_code} {response.text}")

    result = response.json()
    print(f"Total devices in group '{group_name}': {result['total']}")
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
    parser.add_argument(
        "--group-name",
        default=DEFAULT_GROUP_NAME,
        help="full hierarchical NDG name, e.g. 'Location#All Locations'",
    )
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--size", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    with httpx.Client(timeout=30.0) as client:
        token = login(client, args.backend_url, args.backend_username, args.backend_password)
        headers = {"Authorization": f"Bearer {token}"}

        list_devices_by_group(
            client,
            args.backend_url,
            headers,
            args.source_id,
            args.group_name,
            page=args.page,
            size=args.size,
        )

    print("\nSUCCESS: Cisco ISE devices-by-group listing via the REST API is working.")


if __name__ == "__main__":
    main()
