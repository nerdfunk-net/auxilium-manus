#!/usr/bin/env python3
"""seed_example_client.py - put ONE example client into the client-data tables of a lab.

WHAT IT IS FOR
    A lab without real clients cannot show whether Ask the Net finds a client by hostname. This
    writes what the ``collect-client-data`` step would have stored for one host, so that
    "What information do you have about pc-example" can be tried:

      * ``example-access``  (MAC table): the MAC on port Gi1/0/7, VLAN 10
      * ``example-core``    (ARP + reverse DNS): the IP address and the FQDN of the host

    The hostname is stored as a fully qualified name, as reverse DNS returns it.

HOW TO RUN
    From ``backend/``, with the project venv active::

        python scripts/seed_example_client.py                 # write (replaces its own rows)
        python scripts/seed_example_client.py --remove        # delete exactly these rows
        python scripts/seed_example_client.py --hostname pc-lab.lab.example.com --ip 10.9.9.9

    It uses the database of the ``.env`` in ``backend/`` (a lab only: it refuses to run unless
    ``ENV=development``), or the one named with ``--database-url``. The rows carry the session
    id ``example-seed``, so ``--remove`` touches nothing else. The example devices are not real:
    give the user ``client_data:read`` and switch on the inventory and addresses sharing
    settings before asking the assistant.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SESSION_ID = "example-seed"
ACCESS_DEVICE = "example-access"
CORE_DEVICE = "example-core"
DEFAULT_MAC = "aabb.cc00.0777"
HOSTNAME_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]{0,253}[A-Za-z0-9])?$")
MAC_RE = re.compile(r"^[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}$")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Put one example client into the client data.")
    parser.add_argument("--hostname", default="pc-example.lab.example.com")
    parser.add_argument("--ip", default="10.0.10.77")
    parser.add_argument("--mac", default=DEFAULT_MAC, help="aabb.ccdd.eeff notation")
    parser.add_argument("--remove", action="store_true", help="delete the example rows only")
    parser.add_argument("--database-url", default=None, help="a scratch database instead of .env")
    args = parser.parse_args(argv)
    if not HOSTNAME_RE.match(args.hostname):
        parser.error("--hostname is not a valid hostname")
    if not MAC_RE.match(args.mac):
        parser.error("--mac must look like aabb.ccdd.eeff")
    try:
        args.ip = str(ipaddress.ip_address(args.ip))
    except ValueError:
        parser.error("--ip is not an IP address")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.database_url and os.environ.get("ENV", "development") != "development":
        print("Refusing: ENV is not 'development'. This script is for a lab.", file=sys.stderr)
        return 2

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from core.models.client_data import (
        ClientDataCollection,
        ClientHostname,
        ClientIpAddress,
        ClientMacAddress,
        ClientPortNeighbor,
    )
    from models.client_data import (
        ClientCollectionStatus,
        ClientHostnameRow,
        ClientIpRow,
        ClientMacRow,
    )
    from repositories.client_data_repository import ClientDataRepository

    if args.database_url:
        session_factory = sessionmaker(bind=create_engine(args.database_url))
    else:
        from core.database import SessionLocal

        session_factory = SessionLocal
    with session_factory() as db:
        if args.remove:
            for model in (
                ClientHostname,
                ClientIpAddress,
                ClientMacAddress,
                ClientPortNeighbor,
                ClientDataCollection,
            ):
                db.query(model).filter(model.session_id == SESSION_ID).delete()
            db.commit()
            print(f"Removed the rows of session {SESSION_ID!r}.")
            return 0

        repo = ClientDataRepository(db)
        now = datetime.now(UTC)
        repo.replace_device_collection(
            session_id=SESSION_ID,
            device_name=ACCESS_DEVICE,
            device_ip=None,
            collected_at=now,
            ip_rows=[],
            mac_rows=[ClientMacRow(mac_address=args.mac, vlan="10", port="Gi1/0/7")],
            hostname_rows=[],
            status=ClientCollectionStatus(arp_status="skipped", mac_status="ok"),
            keep_sessions=5,
        )
        repo.replace_device_collection(
            session_id=SESSION_ID,
            device_name=CORE_DEVICE,
            device_ip=None,
            collected_at=now,
            ip_rows=[
                ClientIpRow(ip_address=args.ip, mac_address=args.mac, interface="Vlan10", vlan="10")
            ],
            mac_rows=[],
            hostname_rows=[ClientHostnameRow(ip_address=args.ip, hostname=args.hostname)],
            status=ClientCollectionStatus(arp_status="ok", mac_status="skipped"),
            keep_sessions=5,
        )
    short = args.hostname.split(".")[0]
    print(f"Wrote {args.hostname} / {args.ip} / {args.mac} (session {SESSION_ID!r}).")
    print(f"Ask Ask the Net: 'What information do you have about {short}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
