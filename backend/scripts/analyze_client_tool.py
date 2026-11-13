#!/usr/bin/env python3
"""analyze_client_tool.py - find out why the Ask the Net client-data tools are slow.

WHAT IT IS FOR
    A question like "Do you see the IP address 1.2.3.4 in the client data?" makes the assistant
    call ``find_host``, which runs ``find_client`` (the client-data tables in PostgreSQL) and
    ``find_aci_endpoint`` (the APIC) side by side. If it hangs until the turn budget ends, this
    script shows WHICH half is slow and WHY, without a model and without changing any data.

HOW TO RUN
    From ``backend/``, with the project venv active (``source ../.venv/bin/activate``)::

        python scripts/analyze_client_tool.py <command> [value] [options]

    It reads the database of the ``.env`` in ``backend/`` (so run it where the problem is), or
    the database you name with ``--database-url``. ``value`` is any IPv4/IPv6 address, MAC
    address or hostname; the plan is the same shape whichever you pick.

THE USUAL ORDER (production, where it is slow)
    1. python scripts/analyze_client_tool.py tables
         How big is the data? Which devices are biggest? Are the planner statistics fresh?
    2. python scripts/analyze_client_tool.py plan 1.2.3.4 --timeout 300
         Why is the client-data query slow? (join-filter rows and bad row estimates)
    3. python scripts/analyze_client_tool.py tools 1.2.3.4 --user-id 1
         Which half of find_host takes the time: the client data or the ACI lookup?
         (--user-id: a user who holds client_data:read and sources.aci:read.)
    Or all of it at once:  ... all 1.2.3.4 --user-id 1

NO PRODUCTION DATA IN THE LAB? COPY ONLY ITS SHAPE
    1. Production:  python scripts/analyze_client_tool.py export --out profile.json --value 1.2.3.4
         Writes counts and distributions only (no device name, address, MAC, port or hostname).
         Check the file, then copy it to the lab.
    2. Lab, with an EMPTY scratch database (not your real lab database):
         python scripts/analyze_client_tool.py synth --profile profile.json \
             --database-url postgresql+psycopg://USER:PASSWORD@HOST:5432/scratch
         python scripts/analyze_client_tool.py plan 1.2.3.4 \
             --database-url postgresql+psycopg://USER:PASSWORD@HOST:5432/scratch --timeout 300
       The "reference" that ``synth`` prints is the production timing from step 1; the lab
       plan should be of the same kind and about as slow.

COMMANDS
    tables   Row counts of the client_* tables, when each was last analysed, and the devices
             with the most ARP rows x MAC rows (the product the slow join works through).
    plan     EXPLAIN ANALYZE of the exact count and data queries find_client runs. Prints the
             join filters that threw away rows and the nodes whose row estimate is 100x or
             more too low. ``--no-analyze`` shows the plan without running it, ``--full`` the
             whole plan.
    time     The repository call alone, ``--runs`` times (shows warm-up and plan caching).
    tools    The real tools under a timeout, in phases: find_client; the ACI half (sources,
             Redis rate budget, each source's endpoint lookup); find_aci_endpoint; find_host.
             Uses the chat's readers with a fully opted-in sharing policy.
    all      tables + plan + time (+ tools when --user-id is given).
    export   Write the anonymous shape profile (needs --out; --value adds a timing reference).
    synth    Fill an empty scratch database from a profile (needs --profile and --database-url).

OPTIONS
    --timeout N       Seconds allowed per query or tool (default 120).
    --runs N          Repetitions for ``time`` (default 3).
    --user-id N       User for ``tools`` (client_data:read and sources.aci:read).
    --database-url U  Use this PostgreSQL database instead of the application's.
    --out FILE / --profile FILE / --seed N     For export / synth.
    --value V         The value, for commands where you prefer an option to an argument.
    -v                Show the application's own log lines.

HOW TO READ THE RESULT
    plan:  "Rows removed by join filters" in the hundreds of millions, plus nodes marked
           "x10,000 estimated 25 actual 250000", mean PostgreSQL picked a nested loop from a
           wrong row estimate: the query shape is the cause, not the amount of data.
           Small numbers and a quick finish: the client-data query is not the problem.
           Since 2026-11-13 a lookup by IP, MAC, hostname, device, port, VLAN or VRF is narrowed
           to the MACs it can match and runs with nested loops disabled (doc/CLIENT_DATA.md "Cost
           of a lookup"): expect a few thousand removed rows at most and a finish in well under
           a second. Hundreds of millions again means that protection was lost.
    tables: ``modified_since_analyze`` far above ``live`` means stale statistics (run ANALYZE).
    time:  a first run much slower than the next ones points to cold caches or JIT.
    tools: the line that says TIMEOUT names the phase that hangs. If find_client is quick and
           the ACI phases are not, look at the APIC (its timeout, its size), not at the data.

SAFETY
    Every command except ``synth`` only reads: SELECT and EXPLAIN inside READ ONLY
    transactions. ``synth`` writes only to the database you name, creates the client_* tables
    there if missing, and refuses a target whose tables already hold rows. Nothing is sent to
    a model. The output of ``tables``, ``plan``, ``time`` and ``tools`` shows device names,
    addresses and ports of your network: redact it before sharing it outside your team.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import create_engine, event, func, select, text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from core.models.client_data import (  # noqa: E402
    ClientDataCollection,
    ClientHostname,
    ClientIpAddress,
    ClientMacAddress,
    ClientPortNeighbor,
)
from repositories.client_data_query_repository import ClientDataQueryRepository  # noqa: E402

_MODELS = (
    ClientDataCollection,
    ClientIpAddress,
    ClientMacAddress,
    ClientHostname,
    ClientPortNeighbor,
)
_PAGE = 50  # the page size find_client fetches
_ESTIMATE_FACTOR = 100  # report nodes whose actual rows exceed the estimate by this factor
_NODE = re.compile(
    r"^\s*(?:->\s+)?(?P<name>.*?)\s+\(cost=\S+ rows=(?P<est>\d+) width=\d+\)"
    r"\s+\(actual (?:time=\S+ )?rows=(?P<act>[\d.]+) loops=(?P<loops>\d+)\)"
)
_REMOVED = re.compile(r"Rows Removed by Join Filter: (\d+)")


class _Captured(Exception):  # noqa: N818 - control flow, not an error
    """Raised inside the cursor hook once the statement we wanted is captured."""


def _engine(url: str | None) -> Engine:
    if url:
        return create_engine(url)
    from core.database import engine  # the application's own engine  # noqa: PLC0415

    return engine


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


# -- tables ------------------------------------------------------------------------------------


def cmd_tables(engine: Engine) -> None:
    _section("Row counts")
    with Session(engine) as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        for model in _MODELS:
            count = db.execute(select(func.count()).select_from(model)).scalar()
            print(f"{model.__tablename__:28} {count:>10}")

        _section("Planner statistics (stale statistics make bad plans)")
        names = [model.__tablename__ for model in _MODELS]
        stats = db.execute(
            text(
                "SELECT relname, n_live_tup, n_mod_since_analyze, "
                "COALESCE(last_analyze, last_autoanalyze) AS analyzed "
                "FROM pg_stat_user_tables WHERE relname = ANY(:names) ORDER BY relname"
            ),
            {"names": names},
        )
        for row in stats:
            print(
                f"{row.relname:28} live={row.n_live_tup:>9} modified_since_analyze="
                f"{row.n_mod_since_analyze:>9} last_analyzed={row.analyzed}"
            )

        _section("Largest devices (current collections)")
        coverage = ClientDataQueryRepository(db).get_collections()
        # The slow join compares every MAC row of a device with every ARP row of it.
        for row in coverage:
            row["pairs"] = int(row["arp_rows"]) * int(row["mac_rows"])
        coverage.sort(key=lambda r: r["pairs"], reverse=True)
        print(f"devices with a current collection: {len(coverage)}")
        print(f"{'device':32} {'arp_rows':>9} {'mac_rows':>9} {'arp*mac':>14}")
        for row in coverage[:10]:
            print(
                f"{row['device_name']:32} {row['arp_rows']:>9} {row['mac_rows']:>9} "
                f"{row['pairs']:>14}"
            )


# -- plan --------------------------------------------------------------------------------------


def _capture_statements(engine: Engine, value: str) -> dict[str, tuple[str, Any]]:
    """The count and the data statement ``find_client`` runs for *value*, without running them.

    The count statement is swapped for ``SELECT 1`` so the repository goes on to build the data
    statement, which is captured and aborted.
    """
    captured: dict[str, tuple[str, Any]] = {}

    def hook(_conn: Any, _cursor: Any, statement: str, parameters: Any, *_: Any) -> Any:
        if "count(*)" in statement.lower() and "count" not in captured:
            captured["count"] = (statement, parameters)
            return "SELECT 1", {}
        if "count" in captured and "data" not in captured:
            captured["data"] = (statement, parameters)
            raise _Captured
        return statement, parameters

    event.listen(engine, "before_cursor_execute", hook, retval=True)
    try:
        with Session(engine) as db:
            try:
                ClientDataQueryRepository(db).get_client_data(
                    **_filter_for(value), exact=True, likely_first=True, page=1, page_size=_PAGE
                )
            except Exception:  # noqa: BLE001 - the hook's abort arrives wrapped by SQLAlchemy
                if "data" not in captured:
                    raise
    finally:
        event.remove(engine, "before_cursor_execute", hook)
    return captured


def _filter_for(value: str) -> dict[str, Any]:
    """The filter find_client would use (it classifies the value the same way)."""
    from services.ai_assistant.tools.client_data_tools import _classify  # noqa: PLC0415

    candidates = _classify(value)
    if not candidates:
        raise SystemExit(f"'{value}' is neither a MAC address, an IP address nor a hostname")
    key, found = candidates[0]
    return {key: found}


def _summarize_plan(lines: list[str]) -> int:
    """Print the plan summary; returns the rows the join filters removed in total."""
    removed = [(int(m.group(1)), line.strip()) for line in lines if (m := _REMOVED.search(line))]
    # Report the join nodes whose filter discarded rows, with the node line above them.
    print("\nJoin filters that threw rows away:")
    shown = False
    for index, line in enumerate(lines):
        if (m := _REMOVED.search(line)) and int(m.group(1)) >= 100_000:
            node = next(
                (lines[i].strip() for i in range(index, -1, -1) if "(cost=" in lines[i]), "?"
            )
            print(f"  {int(m.group(1)):>14,}  {node[:110]}")
            shown = True
    if not shown:
        print("  none above 100,000 rows")
    worst: list[tuple[float, str, int, int]] = []
    for line in lines:
        if not (m := _NODE.match(line)):
            continue
        est, act, loops = int(m["est"]), float(m["act"]), int(m["loops"])
        total = act * loops
        if total >= max(est, 1) * _ESTIMATE_FACTOR and total >= 1000:
            worst.append((total / max(est, 1), m["name"], est, int(total)))
    print(f"\nNodes with actual rows >= {_ESTIMATE_FACTOR}x the estimate (planner is guessing):")
    for ratio, name, est, act in sorted(worst, reverse=True)[:8]:
        print(f"  x{ratio:>9,.0f}  estimated {est:>6}  actual {act:>9}  {name[:70]}")
    if not worst:
        print("  none")
    total_removed = sum(n for n, _ in removed)
    if removed:
        print(f"\nTotal rows removed by join filters: {total_removed:,}")
    return total_removed


def _explain(engine: Engine, statement: str, params: Any, timeout_s: int, analyze: bool) -> None:
    prefix = "EXPLAIN (ANALYZE, BUFFERS, TIMING OFF) " if analyze else "EXPLAIN "
    with engine.connect() as conn:
        with conn.begin():
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_s * 1000)}")
            started = time.monotonic()
            try:
                lines = [r[0] for r in conn.exec_driver_sql(prefix + statement, params)]
            except Exception as exc:  # noqa: BLE001 - report and fall back to the plain plan
                print(f"stopped after {time.monotonic() - started:.1f}s: {type(exc).__name__}")
                lines = []
        if analyze and not lines:
            print("The query did not finish within the timeout: showing the plan only.")
            with conn.begin():
                conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                lines = [r[0] for r in conn.exec_driver_sql("EXPLAIN " + statement, params)]
            print("\n".join(line[:170] for line in lines))
            return
    print(f"finished in {time.monotonic() - started:.1f}s")
    if analyze:
        _summarize_plan(lines)
    print("\nFull plan:" if analyze else "")
    print("\n".join(line[:170] for line in lines))


def cmd_plan(engine: Engine, value: str, timeout_s: int, analyze: bool, full: bool) -> None:
    captured = _capture_statements(engine, value)
    for name in ("count", "data"):
        _section(f"{name} query for '{value}' ({'ANALYZE' if analyze else 'plan only'})")
        statement, params = captured[name]
        if full:
            _explain(engine, statement, params, timeout_s, analyze)
        else:
            _explain_summary_only(engine, statement, params, timeout_s, analyze)


def _explain_summary_only(
    engine: Engine, statement: str, params: Any, timeout_s: int, analyze: bool
) -> None:
    """Like ``_explain`` but without dumping the (very long) plan unless ``--full``."""
    import contextlib  # noqa: PLC0415
    import io  # noqa: PLC0415

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _explain(engine, statement, params, timeout_s, analyze)
    output = buffer.getvalue()
    print(output.split("\nFull plan:")[0].rstrip())
    print("\n(use --full for the whole plan)")


# -- export / synth ----------------------------------------------------------------------------


def _reference(engine: Engine, value: str, timeout_s: int) -> dict[str, Any]:
    """How long the count query took here, and how many rows its join filters threw away."""
    statement, params = _capture_statements(engine, value)["count"]
    started = time.monotonic()
    with engine.connect() as conn, conn.begin():
        conn.exec_driver_sql("SET TRANSACTION READ ONLY")
        conn.exec_driver_sql(f"SET LOCAL statement_timeout = {int(timeout_s * 1000)}")
        try:
            lines = [
                r[0]
                for r in conn.exec_driver_sql("EXPLAIN (ANALYZE, TIMING OFF) " + statement, params)
            ]
        except Exception:  # noqa: BLE001 - a timeout is a result, not a failure
            return {"finished": False, "seconds": round(time.monotonic() - started, 1)}
    removed = sum(int(m.group(1)) for line in lines if (m := _REMOVED.search(line)))
    return {
        "finished": True,
        "seconds": round(time.monotonic() - started, 1),
        "rows_removed_by_join_filters": removed,
        "value_kind": next(iter(_filter_for(value))),
    }


def cmd_export(engine: Engine, out: Path, value: str | None, timeout_s: int) -> None:
    from client_data_profile import export_profile  # noqa: PLC0415

    profile = export_profile(engine)
    if value:
        print(f"timing the lookup here (up to {timeout_s}s) ...")
        profile["reference"] = _reference(engine, value, timeout_s)
    out.write_text(json.dumps(profile, indent=1) + "\n")
    shape = profile["global"]
    print(f"wrote {out}: {len(profile['devices'])} devices, no names or addresses")
    print(f"  distinct MACs: {shape['distinct_macs_in_mac_tables']}")
    print(f"  rows (all sessions): {shape['total_rows_all_sessions']}")
    if "reference" in profile:
        print(f"  reference: {profile['reference']}")


def cmd_synth(engine: Engine, profile_path: Path, seed: int) -> None:
    from client_data_profile import synthesize  # noqa: PLC0415

    profile = json.loads(profile_path.read_text())
    started = time.monotonic()
    totals = synthesize(engine, profile, seed)
    print(f"generated in {time.monotonic() - started:.0f}s: {totals}")
    reference = profile.get("reference")
    if reference:
        print(f"production reference: {reference}")
    print("now run:  analyze_client_tool.py plan <any IP> --database-url <this database>")


# -- time --------------------------------------------------------------------------------------


def cmd_time(engine: Engine, value: str, runs: int, timeout_s: int) -> None:
    _section(f"Repository call for '{value}' ({runs} runs, timeout {timeout_s}s each)")
    for run in range(1, runs + 1):
        with Session(engine) as db:
            db.execute(text("SET TRANSACTION READ ONLY"))
            db.execute(text(f"SET LOCAL statement_timeout = {int(timeout_s * 1000)}"))
            started = time.monotonic()
            try:
                rows, total = ClientDataQueryRepository(db).get_client_data(
                    **_filter_for(value), exact=True, likely_first=True, page=1, page_size=_PAGE
                )
                outcome = f"rows={len(rows)} total={total}"
            except Exception as exc:  # noqa: BLE001
                outcome = f"FAILED {type(exc).__name__}"
        print(f"run {run}: {time.monotonic() - started:6.1f}s  {outcome}")


# -- tools -------------------------------------------------------------------------------------


async def _timed(label: str, awaitable: Any, timeout_s: float) -> Any:
    started = time.monotonic()
    try:
        result = await asyncio.wait_for(awaitable, timeout=timeout_s)
    except TimeoutError:
        print(f"{label:42} TIMEOUT after {time.monotonic() - started:6.1f}s")
        return None
    except Exception as exc:  # noqa: BLE001
        print(
            f"{label:42} {type(exc).__name__}: {str(exc)[:80]} ({time.monotonic() - started:.1f}s)"
        )
        return None
    print(f"{label:42} ok      {time.monotonic() - started:6.1f}s")
    return result


def _show(output: Any) -> None:
    if output is not None:
        print(f"    -> {_preview(output)}")


def _preview(output: Any) -> str:
    content = getattr(output, "content", "")
    try:
        parsed = json.loads(content)
    except ValueError:
        return content[:200]
    if isinstance(parsed, dict) and {"client_data", "aci"} <= parsed.keys():
        return (
            f"client_data={parsed['client_data'].get('status')} aci={parsed['aci'].get('status')}"
        )
    return f"{len(content)} characters, is_error={getattr(output, 'is_error', None)}"


async def _tools(value: str, user_id: int, timeout_s: float) -> None:
    from services.ai_assistant.aci_reader import DbAciReader  # noqa: PLC0415
    from services.ai_assistant.client_data_reader import DbClientDataReader  # noqa: PLC0415
    from services.ai_assistant.data_sharing import SharingPolicy  # noqa: PLC0415
    from services.ai_assistant.redaction import Redactor  # noqa: PLC0415
    from services.ai_assistant.tools.aci_lookup_tools import (  # noqa: PLC0415
        FindEndpointInput,
        _find_endpoint,
    )
    from services.ai_assistant.tools.aci_tools import (  # noqa: PLC0415
        ACI_READER_KEY,
        _within_budget,
    )
    from services.ai_assistant.tools.base import ToolContext  # noqa: PLC0415
    from services.ai_assistant.tools.client_data_tools import (  # noqa: PLC0415
        CLIENT_DATA_READER_KEY,
        FindClientInput,
        _find_client,
    )
    from services.ai_assistant.tools.host_lookup_tools import (  # noqa: PLC0415
        FindHostInput,
        _find_host,
    )

    aci_reader = DbAciReader(user_id)
    ctx = ToolContext(
        user_id=user_id,
        redactor=Redactor(),
        extras={
            ACI_READER_KEY: aci_reader,
            CLIENT_DATA_READER_KEY: DbClientDataReader(user_id),
        },
        sharing=SharingPolicy(inventory=True, addresses=True),
    )
    _section(f"Tools for '{value}' (user {user_id}, timeout {timeout_s:.0f}s each)")

    out = await _timed(
        "find_client (client data only)",
        _find_client(ctx, FindClientInput(address=value)),
        timeout_s,
    )
    _show(out)

    print("\nACI half, in phases:")
    sources = await _timed(
        "  reader.sources() (RBAC, source, login prep)", aci_reader.sources(), timeout_s
    )
    await _timed("  rate budget (Redis reserve)", _within_budget(user_id, 1), timeout_s)
    for source in sources or ():
        endpoint = await _timed(
            f"  source '{source.source_id}' endpoints.find()",
            source.endpoints.find(value),
            timeout_s,
        )
        if endpoint is not None:
            print(f"    -> {len(endpoint)} endpoint(s)")
    out = await _timed(
        "find_aci_endpoint (whole tool)",
        _find_endpoint(ctx, FindEndpointInput(address=value, source=None)),
        timeout_s,
    )
    _show(out)

    print()
    out = await _timed(
        "find_host (the tool the chat calls)",
        _find_host(ctx, FindHostInput(address=value, source=None)),
        timeout_s,
    )
    _show(out)


# -- main --------------------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "command", choices=("tables", "plan", "time", "tools", "all", "export", "synth")
    )
    parser.add_argument("value", nargs="?", help="a MAC address, an IP address or a hostname")
    parser.add_argument(
        "--user-id", type=int, help="user for the 'tools' step (needs the permissions)"
    )
    parser.add_argument(
        "--timeout", type=int, default=120, help="seconds per query or tool (default 120)"
    )
    parser.add_argument("--runs", type=int, default=3, help="repetitions for 'time' (default 3)")
    parser.add_argument(
        "--no-analyze", action="store_true", help="'plan': show the plan, run nothing"
    )
    parser.add_argument("--full", action="store_true", help="'plan': print the whole plan")
    parser.add_argument("--database-url", help="override the application's database")
    parser.add_argument("--value", dest="value_option", help="same as the positional value")
    parser.add_argument("--out", type=Path, help="'export': the profile file to write")
    parser.add_argument("--profile", type=Path, help="'synth': the profile file to read")
    parser.add_argument("--seed", type=int, default=1, help="'synth': random seed (default 1)")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show the application's own log lines"
    )
    args = parser.parse_args()
    args.value = args.value or args.value_option

    if args.command in ("plan", "time", "tools", "all") and not args.value:
        parser.error(f"'{args.command}' needs a value to look up")
    if args.command == "export" and not args.out:
        parser.error("'export' needs --out")
    if args.command == "synth" and not (args.profile and args.database_url):
        parser.error("'synth' needs --profile and an explicit --database-url (a scratch database)")
    if args.command in ("tools", "all") and args.user_id is None:
        if args.command == "tools":
            parser.error("'tools' needs --user-id")
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)

    engine = _engine(args.database_url)
    if engine.dialect.name != "postgresql":
        print("This script analyses PostgreSQL plans; the database is not PostgreSQL.")
        return 2
    if args.command == "export":
        cmd_export(engine, args.out, args.value, args.timeout)
        return 0
    if args.command == "synth":
        cmd_synth(engine, args.profile, args.seed)
        return 0
    if args.command in ("tables", "all"):
        cmd_tables(engine)
    if args.command in ("plan", "all"):
        cmd_plan(engine, args.value, args.timeout, not args.no_analyze, args.full)
    if args.command in ("time", "all"):
        cmd_time(engine, args.value, args.runs, args.timeout)
    if args.command in ("tools", "all") and args.user_id is not None:
        asyncio.run(_tools(args.value, args.user_id, float(args.timeout)))
    elif args.command == "all":
        print("\n(skipped 'tools': pass --user-id to run the real tools)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
