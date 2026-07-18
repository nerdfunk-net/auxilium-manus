#!/usr/bin/env python3
"""Manual smoke test for listing Cisco ISE Network Device Groups.

Companion to ``ise_test_ndg_add.py``/``ise_test_ndg_update.py``/
``ise_test_ndg_delete.py``. Drives the manus backend's REST API (not the
ISE ERS API directly) to list network device groups via
``GET /sources/ise/{source_id}/network-device-groups/``, with optional
pagination and ISE-native ``filter`` passthrough.

Usage (from ``backend/``, with the project venv active and the backend
running, e.g. via ``python start.py``)::

    ../.venv/bin/python scripts/ise_test_ndg_list.py

    # Filter and page through results
    ../.venv/bin/python scripts/ise_test_ndg_list.py --filter "name.CONTAINS.Location"
    ../.venv/bin/python scripts/ise_test_ndg_list.py --size 2 --all

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


def list_groups(
    client: httpx.Client,
    backend_url: str,
    headers: dict[str, str],
    source_id: str,
    *,
    page: int,
    size: int,
    filter_: str | None,
    fetch_all: bool,
) -> None:
    _step(f"List network device groups for ISE source '{source_id}'")

    total_seen = 0
    current_page = page
    while True:
        params: dict[str, int | str] = {"page": current_page, "size": size}
        if filter_:
            params["filter"] = filter_

        response = client.get(
            f"{backend_url}/api/sources/ise/{source_id}/network-device-groups/",
            headers=headers,
            params=params,
        )
        if response.status_code != 200:
            _fail(f"failed to list network device groups: {response.status_code} {response.text}")

        result = response.json()
        if current_page == page:
            print(f"Total network device groups in ISE: {result['total']}")

        for group in result["resources"]:
            print(f"  - {group['name']} (id={group['id']}) — {group.get('description', '')}")
        total_seen += len(result["resources"])

        if not fetch_all or not result.get("next_page"):
            break
        current_page += 1

    if fetch_all:
        print(f"\nFetched {total_seen} group(s) across {current_page - page + 1} page(s).")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument("--backend-username", default=DEFAULT_BACKEND_USERNAME)
    parser.add_argument("--backend-password", default=DEFAULT_BACKEND_PASSWORD)
    parser.add_argument("--source-id", default=DEFAULT_SOURCE_ID)
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--size", type=int, default=20)
    parser.add_argument(
        "--filter",
        default=None,
        help="ISE-native filter, e.g. 'name.CONTAINS.Location' (passed through verbatim)",
    )
    parser.add_argument(
        "--all", dest="fetch_all", action="store_true", help="page through all results"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    with httpx.Client(timeout=30.0) as client:
        token = login(client, args.backend_url, args.backend_username, args.backend_password)
        headers = {"Authorization": f"Bearer {token}"}

        list_groups(
            client,
            args.backend_url,
            headers,
            args.source_id,
            page=args.page,
            size=args.size,
            filter_=args.filter,
            fetch_all=args.fetch_all,
        )

    print("\nSUCCESS: Cisco ISE network device group listing via the REST API is working.")


if __name__ == "__main__":
    main()
