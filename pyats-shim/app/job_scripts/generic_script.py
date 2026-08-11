"""Generic AEtest script run by every pyATS shim job.

CommonSetup connects to every device in the testbed; the single Testcase
loops device x command, calling device.execute() or device.parse() per the
requested operation; CommonCleanup disconnects and writes the collected
results to PYATS_SHIM_RESULT_FILE as JSON. Per-device connect failures and
per-command failures are captured in the results dict rather than raised, so
one bad device or command doesn't abort the rest of the batch.
"""

from __future__ import annotations

import json
import logging

from pyats import aetest

logger = logging.getLogger(__name__)


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
            try:
                device.connect(log_stdout=False, learn_hostname=False)
            except Exception as exc:  # noqa: BLE001 - reported per-device, not raised
                logger.warning("Failed to connect to device %s: %s", name, exc)
                results[name]["success"] = False
                results[name]["error"] = str(exc)


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
                    entry["error"] = str(exc)
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
