"""Generic AEtest script run by every pyATS shim job.

CommonSetup connects to every device in the testbed; the single Testcase
loops device x command, calling device.execute() or device.parse() per the
requested operation; CommonCleanup disconnects and writes the collected
results to PYATS_SHIM_RESULT_FILE as JSON. Per-device connect failures and
per-command failures are captured in the results dict rather than raised, so
one bad device or command doesn't abort the rest of the batch.

Per-device connect start/success/failure is logged with a ``[pyats-connect]``
marker so ``JobRunner`` can pull just those lines out of the subprocess's
stdout/stderr and forward them into the shim's own log stream -- the rest of
this process's output (which can include raw device command output) is never
forwarded, to avoid leaking device config content into logs.

This module is never imported as part of the ``app`` package: pyATS loads it
via ``FlexImporter`` by absolute file path inside a subprocess whose ``cwd``
is a throwaway work dir, so ``/app`` is never on ``sys.path`` here (confirmed
by a real run: ``from app.log_markers import ...`` raised ``ModuleNotFoundError:
No module named 'app'``). The marker string is therefore duplicated from
``app/log_markers.py`` rather than imported -- keep the two in sync.
"""

from __future__ import annotations

import json
import logging
import time

from pyats import aetest

logger = logging.getLogger(__name__)

CONNECT_MARKER = "[pyats-connect]"  # keep in sync with app/log_markers.py


def _device_host(device) -> str:
    try:
        return str(device.connections["cli"]["ip"])
    except Exception:  # noqa: BLE001 - best-effort, logging only
        return "unknown"


def _exception_chain(exc: BaseException) -> str:
    """Join an exception with its ``__cause__``/``__context__`` chain.

    pyATS/Unicon wrap the real failure (e.g. a state-machine timeout) in a
    generic top-level ``ConnectionError("failed to connect to <name>")``;
    ``str(exc)`` alone only shows that generic wrapper, discarding the chained
    original error that actually explains what went wrong.
    """
    parts = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(f"{type(current).__name__}: {current}")
        current = current.__cause__ or current.__context__
    return " <- caused by: ".join(parts)


class CommonSetup(aetest.CommonSetup):
    @aetest.subsection
    def load_request(self, request_file):
        with open(request_file) as handle:
            request = json.load(handle)
        self.parent.parameters.update(
            operation=request["operation"],
            commands=request["commands"],
            results={},
        )

    @aetest.subsection
    def connect_devices(self, testbed, results):
        for name, device in testbed.devices.items():
            results[name] = {"success": True, "error": None, "commands": {}}
            host = _device_host(device)
            logger.info("%s connecting name=%s host=%s", CONNECT_MARKER, name, host)
            started = time.monotonic()
            try:
                # learn_hostname=True: testbed device names are opaque inventory
                # IDs (e.g. "list-<uuid>"), never the device's real CLI hostname
                # -- with learn_hostname=False Unicon keeps expecting prompt
                # patterns built around that inventory ID instead of adopting
                # the hostname it actually observes, and the state machine
                # never matches a real prompt (confirmed via `pyats shell`:
                # "%UNICON-WARNING: Invalid hostname detected: found LAB,
                # expected list-...", followed by a hang and eventual
                # "Failed while bringing device to 'any' state").
                device.connect(log_stdout=False, learn_hostname=True)
            except Exception as exc:  # noqa: BLE001 - reported per-device, not raised
                elapsed = time.monotonic() - started
                detail = _exception_chain(exc)
                logger.warning(
                    "%s failed name=%s host=%s elapsed=%.1fs error=%s",
                    CONNECT_MARKER,
                    name,
                    host,
                    elapsed,
                    detail,
                )
                results[name]["success"] = False
                results[name]["error"] = detail
            else:
                elapsed = time.monotonic() - started
                logger.info(
                    "%s connected name=%s host=%s elapsed=%.1fs",
                    CONNECT_MARKER,
                    name,
                    host,
                    elapsed,
                )


class RunRequestedOperation(aetest.Testcase):
    @aetest.test
    def run_commands(self, testbed, operation, commands, results):
        for name, device in testbed.devices.items():
            if not results[name]["success"]:
                continue
            for command in commands:
                entry = {"raw": None, "parsed": None, "error": None}
                try:
                    if operation == "parse":
                        entry["parsed"] = device.parse(command)
                    else:
                        entry["raw"] = device.execute(command)
                except Exception as exc:  # noqa: BLE001 - reported per-command, not raised
                    entry["error"] = _exception_chain(exc)
                results[name]["commands"][command] = entry


class CommonCleanup(aetest.CommonCleanup):
    @aetest.subsection
    def disconnect_devices(self, testbed):
        for name, device in testbed.devices.items():
            try:
                if device.is_connected():
                    device.disconnect()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                logger.warning("Failed to cleanly disconnect device %s", name)

    @aetest.subsection
    def write_results(self, result_file, results):
        with open(result_file, "w") as handle:
            json.dump(results, handle)


if __name__ == "__main__":
    aetest.main()
