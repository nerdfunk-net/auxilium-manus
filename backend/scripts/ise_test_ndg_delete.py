#!/usr/bin/env python3
"""Manual smoke test for deleting Cisco ISE Network Device Groups.

Companion to ``ise_test_ndg_add.py`` and ``ise_test_ndg_update.py``. Drives
the manus backend's REST API (not the ISE ERS API directly) to delete the
three groups those scripts create/update
(``Location#All Locations#All-001``, ``new-root#new-root#location-001``,
and ``new-root#new-root``), children before parents, then confirms each is
gone by re-fetching it (expects 404).

Usage (from ``backend/``, with the project venv active and the backend
running)::

    ../.venv/bin/python scripts/ise_test_ndg_delete.py

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

LOCATION_CHILD_FULL_NAME = "Location#All Locations#All-001"
NEW_ROOT_FULL_NAME = "new-root#new-root"
ROOT_CHILD_FULL_NAME = "new-root#new-root#location-001"

# Children before parents, so ISE never has to delete a group with children.
GROUPS_TO_DELETE = [
    LOCATION_CHILD_FULL_NAME,
    ROOT_CHILD_FULL_NAME,
    NEW_ROOT_FULL_NAME,
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


def get_group_id_by_name(
    client: httpx.Client, backend_url: str, headers: dict[str, str], source_id: str, full_name: str
) -> str | None:
    response = client.get(
        f"{backend_url}/api/sources/ise/{source_id}/network-device-groups/name/"
        f"{quote(full_name, safe='')}",
        headers=headers,
    )
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        _fail(f"failed to look up group '{full_name}': {response.status_code} {response.text}")
    return response.json()["id"]


def delete_group(
    client: httpx.Client, backend_url: str, headers: dict[str, str], source_id: str, full_name: str
) -> None:
    _step(f"Delete '{full_name}'")
    group_id = get_group_id_by_name(client, backend_url, headers, source_id, full_name)
    if group_id is None:
        print(f"Group '{full_name}' does not exist, nothing to delete.")
        return

    print(f"Found group id={group_id}")
    response = client.delete(
        f"{backend_url}/api/sources/ise/{source_id}/network-device-groups/{group_id}",
        headers=headers,
    )
    if response.status_code != 204:
        _fail(f"failed to delete group: {response.status_code} {response.text}")
    print("Delete request accepted (204 No Content).")

    still_there = get_group_id_by_name(client, backend_url, headers, source_id, full_name)
    if still_there is not None:
        _fail(f"group '{full_name}' still exists after delete (id={still_there})")
    print(f"Confirmed '{full_name}' is gone.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument("--backend-username", default=DEFAULT_BACKEND_USERNAME)
    parser.add_argument("--backend-password", default=DEFAULT_BACKEND_PASSWORD)
    parser.add_argument("--source-id", default=DEFAULT_SOURCE_ID)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    with httpx.Client(timeout=30.0) as client:
        token = login(client, args.backend_url, args.backend_username, args.backend_password)
        headers = {"Authorization": f"Bearer {token}"}

        for full_name in GROUPS_TO_DELETE:
            delete_group(client, args.backend_url, headers, args.source_id, full_name)

    print("\nSUCCESS: Cisco ISE network device group deletion via the REST API is working.")


if __name__ == "__main__":
    main()
