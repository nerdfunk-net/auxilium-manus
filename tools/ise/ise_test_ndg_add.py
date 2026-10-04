#!/usr/bin/env python3
"""Manual smoke test for creating Cisco ISE Network Device Groups.

Companion to the ``ise_test*.py`` device scripts. Drives the manus
backend's REST API (not the ISE ERS API directly) to create three network
device groups:

1. ``All-001`` — a child of the pre-existing ``Location#All Locations``
   group (via ``POST /sources/ise/{source_id}/location-groups``).
2. ``new-root`` — a brand-new root group / category (via
   ``POST /sources/ise/{source_id}/network-device-groups/roots``).
3. ``location-001`` — a child of the new ``new-root`` group (via
   ``POST /sources/ise/{source_id}/network-device-groups/children``).

Idempotent: if a group already exists (by name), it is reused rather than
re-created. Use ``ise_test_ndg_update.py`` to update their descriptions and
``ise_test_ndg_delete.py`` to remove them again.

Usage (from ``backend/``, with the project venv active and the backend
running, e.g. via ``python start.py``)::

    ../.venv/bin/python scripts/ise_test_ndg_add.py

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

# Group names used consistently across the add/update/delete scripts.
LOCATION_PARENT = "All Locations"
LOCATION_CHILD_NAME = "All-001"
LOCATION_CHILD_FULL_NAME = f"Location#{LOCATION_PARENT}#{LOCATION_CHILD_NAME}"

NEW_ROOT_NAME = "new-root"
NEW_ROOT_FULL_NAME = f"{NEW_ROOT_NAME}#{NEW_ROOT_NAME}"

ROOT_CHILD_NAME = "location-001"
ROOT_CHILD_FULL_NAME = f"{NEW_ROOT_FULL_NAME}#{ROOT_CHILD_NAME}"


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


def group_exists(
    client: httpx.Client, backend_url: str, headers: dict[str, str], source_id: str, full_name: str
) -> bool:
    response = client.get(
        f"{backend_url}/api/sources/ise/{source_id}/network-device-groups/name/"
        f"{quote(full_name, safe='')}",
        headers=headers,
    )
    if response.status_code == 200:
        return True
    if response.status_code == 404:
        return False
    _fail(f"failed to look up group '{full_name}': {response.status_code} {response.text}")
    return False  # unreachable, keeps type checkers happy


def create_location_child(
    client: httpx.Client, backend_url: str, headers: dict[str, str], source_id: str
) -> None:
    _step(f"Create Location child '{LOCATION_CHILD_NAME}' under '{LOCATION_PARENT}'")
    if group_exists(client, backend_url, headers, source_id, LOCATION_CHILD_FULL_NAME):
        print(f"Group '{LOCATION_CHILD_FULL_NAME}' already exists, skipping.")
        return

    response = client.post(
        f"{backend_url}/api/sources/ise/{source_id}/location-groups",
        headers=headers,
        json={
            "name": LOCATION_CHILD_NAME,
            "description": "manus test location",
            "parent_group": LOCATION_PARENT,
        },
    )
    if response.status_code != 201:
        _fail(f"failed to create '{LOCATION_CHILD_NAME}': {response.status_code} {response.text}")
    print(f"Created '{response.json()['name']}' (id={response.json()['id']})")


def create_new_root(
    client: httpx.Client, backend_url: str, headers: dict[str, str], source_id: str
) -> None:
    _step(f"Create new root group '{NEW_ROOT_NAME}'")
    if group_exists(client, backend_url, headers, source_id, NEW_ROOT_FULL_NAME):
        print(f"Group '{NEW_ROOT_FULL_NAME}' already exists, skipping.")
        return

    response = client.post(
        f"{backend_url}/api/sources/ise/{source_id}/network-device-groups/roots",
        headers=headers,
        json={"name": NEW_ROOT_NAME, "description": "manus test root group"},
    )
    if response.status_code != 201:
        _fail(f"failed to create root '{NEW_ROOT_NAME}': {response.status_code} {response.text}")
    print(f"Created '{response.json()['name']}' (id={response.json()['id']})")


def create_root_child(
    client: httpx.Client, backend_url: str, headers: dict[str, str], source_id: str
) -> None:
    _step(f"Create child '{ROOT_CHILD_NAME}' under '{NEW_ROOT_FULL_NAME}'")
    if group_exists(client, backend_url, headers, source_id, ROOT_CHILD_FULL_NAME):
        print(f"Group '{ROOT_CHILD_FULL_NAME}' already exists, skipping.")
        return

    response = client.post(
        f"{backend_url}/api/sources/ise/{source_id}/network-device-groups/children",
        headers=headers,
        json={
            "name": ROOT_CHILD_NAME,
            "description": "manus test child of new root",
            "parent_group": NEW_ROOT_FULL_NAME,
        },
    )
    if response.status_code != 201:
        _fail(f"failed to create '{ROOT_CHILD_NAME}': {response.status_code} {response.text}")
    print(f"Created '{response.json()['name']}' (id={response.json()['id']})")


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

        create_location_child(client, args.backend_url, headers, args.source_id)
        create_new_root(client, args.backend_url, headers, args.source_id)
        create_root_child(client, args.backend_url, headers, args.source_id)

    print("\nSUCCESS: Cisco ISE network device group creation via the REST API is working.")


if __name__ == "__main__":
    main()
