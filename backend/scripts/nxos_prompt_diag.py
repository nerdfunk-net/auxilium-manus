"""Diagnose why Netmiko cannot detect the prompt after 'show running-config' on NX-OS.

Run from the project venv, against ONE device at a time:

    source .venv/bin/activate
    python nxos_prompt_diag.py 192.168.178.240 -u <username>
    python nxos_prompt_diag.py 192.168.178.240 -u <username> --no-fast-cli
    python nxos_prompt_diag.py <working-device> -u <username>      # for comparison

The password is prompted for (never passed on the command line). A full raw
session log is written to ./nxos_diag_<host>_<fast|slow>.log -- review it before
sharing, it contains the device's config output.
"""

from __future__ import annotations

import argparse
import getpass
import io
import re
import sys
import time

from netmiko import ConnectHandler
from netmiko.exceptions import ReadTimeout

TAIL_CHARS = 400
PAGING_MARKERS = ("--More--", "---More---")


def _tail(text: str, n: int = TAIL_CHARS) -> str:
    return repr(text[-n:])


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def _terminal_settings(conn: ConnectHandler) -> None:
    _section("Terminal settings as the device sees them")
    for command in ("show terminal | include length|width", "show terminal"):
        try:
            out = conn.send_command(command, read_timeout=30)
        except ReadTimeout as exc:
            print(f"{command!r}: ReadTimeout ({str(exc).splitlines()[1:2]})")
            continue
        print(f"$ {command}")
        print(out[:800])
        return


def _run_show(conn: ConnectHandler, read_timeout: int, cmd_verify: bool) -> str | None:
    _section(f"show running-config (read_timeout={read_timeout}, cmd_verify={cmd_verify})")
    start = time.monotonic()
    output: str | None = None
    try:
        output = conn.send_command(
            "show running-config", read_timeout=read_timeout, cmd_verify=cmd_verify
        )
        print(f"OK after {time.monotonic() - start:.1f}s, {len(output)} chars")
        print("last 400 chars (repr):", _tail(output))
    except ReadTimeout as exc:
        print(f"ReadTimeout after {time.monotonic() - start:.1f}s")
        print("exception first lines:", " | ".join(str(exc).strip().splitlines()[:2]))
    return output


def _analyse_log(log_text: str, prompt: str) -> None:
    _section("Session log analysis")
    print(f"session log size: {len(log_text)} chars")
    hits = [m for m in PAGING_MARKERS if m in log_text]
    print(f"paging markers found: {hits or 'none'}")
    print(f"learned prompt occurrences in log: {log_text.count(prompt)}")
    ansi = re.findall(r"\x1b\[[0-9;?]*[A-Za-z]", log_text)
    print(f"ANSI escape sequences in log: {len(ansi)} (e.g. {sorted(set(ansi))[:5]})")
    print("log tail (repr):", _tail(log_text, 600))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("host")
    parser.add_argument("-u", "--username", required=True)
    parser.add_argument("--read-timeout", type=int, default=180)
    parser.add_argument(
        "--no-fast-cli",
        action="store_true",
        help="disable Netmiko fast_cli (longer sleeps in find_prompt)",
    )
    parser.add_argument(
        "--no-cmd-verify",
        action="store_true",
        help="skip the command-echo wait in send_command",
    )
    args = parser.parse_args()

    password = getpass.getpass(f"Password for {args.username}@{args.host}: ")
    log_buffer = io.BytesIO()
    fast_cli = not args.no_fast_cli

    _section("Connect")
    try:
        conn = ConnectHandler(
            device_type="cisco_nxos",
            host=args.host,
            username=args.username,
            password=password,
            timeout=100,
            session_timeout=60,
            keepalive=30,
            fast_cli=fast_cli,
            session_log=log_buffer,
        )
    except Exception as exc:  # diagnostic script: show whatever failed
        print(f"connect failed: {type(exc).__name__}: {exc}")
        return 1

    try:
        print(f"fast_cli={fast_cli} global_delay_factor={conn.global_delay_factor}")
        print("base_prompt (repr):", repr(conn.base_prompt))
        live_prompt = conn.find_prompt()
        print("find_prompt() now (repr):", repr(live_prompt))
        _terminal_settings(conn)
        _run_show(conn, args.read_timeout, cmd_verify=not args.no_cmd_verify)
        try:
            print("prompt after command (repr):", repr(conn.find_prompt()))
        except Exception as exc:
            print(f"find_prompt after command failed: {type(exc).__name__}: {exc}")
        log_text = log_buffer.getvalue().decode("utf-8", errors="replace")
        _analyse_log(log_text, conn.base_prompt)
    finally:
        try:
            conn.disconnect()
        except Exception:
            pass

    log_path = f"nxos_diag_{args.host}_{'fast' if fast_cli else 'slow'}.log"
    with open(log_path, "w", encoding="utf-8") as handle:
        handle.write(log_buffer.getvalue().decode("utf-8", errors="replace"))
    print(f"\nfull session log written to {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
