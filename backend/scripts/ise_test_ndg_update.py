#!/usr/bin/env python3
"""Manual smoke test for updating Cisco ISE Network Device Group descriptions.

Companion to ``ise_test_ndg_add.py``. Drives the manus backend's REST API
(not the ISE ERS API directly) to update the description of the three
groups that script creates (``Location#All Locations#All-001``,
``new-root#new-root``, and ``new-root#new-root#location-001``), then
re-fetches each to confirm the change while the group's ``name`` and
``othername`` stayed the same.

Sends only ``description`` in the update request on purpose: the manus
backend does a read-merge-write against Cisco ISE's ERS API (``PUT`` there
requires ``name``/``othername`` and would otherwise wipe/reject the group),
so this also exercises that merge path.

Usage (from ``backend/``, with the project venv active, the backend
running, and ``ise_test_ndg_add.py`` already run once)::

    ../.venv/bin/python scripts/ise_test_ndg_update.py

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

GROUPS_TO_UPDATE = [
    (LOCATION_CHILD_FULL_NAME, "manus test location (updated)"),
    (NEW_ROOT_FULL_NAME, "manus test root group (updated)"),
    (ROOT_CHILD_FULL_NAME, "manus test child of new root (updated)"),
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


def get_group_by_name(
    client: httpx.Client, backend_url: str, headers: dict[str, str], source_id: str, full_name: str
) -> dict:
    response = client.get(
        f"{backend_url}/api/sources/ise/{source_id}/network-device-groups/name/"
        f"{quote(full_name, safe='')}",
        headers=headers,
    )
    if response.status_code == 404:
        _fail(f"group '{full_name}' not found. Run ise_test_ndg_add.py first to create it.")
    if response.status_code != 200:
        _fail(f"failed to look up group '{full_name}': {response.status_code} {response.text}")
    return response.json()


def update_description(
    client: httpx.Client,
    backend_url: str,
    headers: dict[str, str],
    source_id: str,
    full_name: str,
    new_description: str,
) -> None:
    _step(f"Update description of '{full_name}'")
    before = get_group_by_name(client, backend_url, headers, source_id, full_name)
    print(f"Found group id={before['id']}, current description='{before.get('description')}'")

    response = client.put(
        f"{backend_url}/api/sources/ise/{source_id}/network-device-groups/{before['id']}",
        headers=headers,
        json={"description": new_description},
    )
    if response.status_code != 200:
        _fail(f"failed to update description: {response.status_code} {response.text}")

    after = response.json()
    if after["description"] != new_description:
        _fail(f"description was not updated as expected: got {after['description']!r}")
    if after["name"] != before["name"] or after["othername"] != before["othername"]:
        _fail(
            "name/othername changed unexpectedly during a description-only update: "
            f"before=({before['name']!r}, {before['othername']!r}) "
            f"after=({after['name']!r}, {after['othername']!r})"
        )
    print(f"Description is now '{after['description']}' — name and othername unchanged.")


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

        for full_name, new_description in GROUPS_TO_UPDATE:
            update_description(
                client, args.backend_url, headers, args.source_id, full_name, new_description
            )

    print(
        "\nSUCCESS: Cisco ISE network device group description update via "
        "the REST API is working."
    )


if __name__ == "__main__":
    main()
