"""Worker for POST /v1/learn-replay: ``python -m app.replay_worker`` (reads JSON on stdin).

Runs in its own process so a hung mock device can be killed by the caller. Writes one JSON line to
stdout: ``{"ok": true, "payload": {"info": ..., "_exclude": [...]}}`` or ``{"ok": false, "error":
"..."}``. The payload has the shape of a learned snapshot, so it can go straight to /v1/diff.
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile

from app.replay_mock import build_mock_data


def _json_safe(value, _depth: int = 0):
    """Same conversion as the job script: keys to strings, sets and tuples to lists."""
    if _depth > 100:
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        return str(
            value
        )  # json.loads rejects NaN and Infinity, which json.dumps would emit
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v, _depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(v, _depth + 1) for v in value]
    return str(value)


def learn(
    os_name: str,
    feature: str,
    commands: list[dict[str, str]],
    workdir: str | None = None,
) -> dict:
    """The learned model. ``workdir`` is owned (and removed) by the caller when given, so a worker
    that is killed leaves nothing behind; without it a temporary directory is used."""
    if workdir is not None:
        return _learn_in(workdir, os_name, feature, commands)
    with tempfile.TemporaryDirectory(prefix="replay-") as tmp:
        return _learn_in(tmp, os_name, feature, commands)


def _learn_in(
    tmp: str, os_name: str, feature: str, commands: list[dict[str, str]]
) -> dict:
    from genie.testbed import load  # lazy: genie only exists inside the container

    with open(os.path.join(tmp, "mock_data.yaml"), "w", encoding="utf-8") as handle:
        handle.write(build_mock_data(commands))
    testbed = load(
        {
            "devices": {
                "R1": {
                    "os": os_name,
                    "type": "router",
                    "credentials": {"default": {"username": "u", "password": "p"}},
                    "connections": {
                        "cli": {
                            "command": (
                                f"mock_device_cli --os {os_name} "
                                f"--mock_data_dir {tmp} --state connect"
                            ),
                            "protocol": "unknown",
                        }
                    },
                }
            }
        }
    )
    device = testbed.devices["R1"]
    device.connect(
        learn_hostname=False,
        init_exec_commands=["term length 0", "term width 0"],
        init_config_commands=[],
        log_stdout=False,
        # Unicon writes a session log per connection (to /tmp by default). Keep it inside the
        # working directory, which the caller removes, so replays leave nothing behind.
        logfile=os.path.join(tmp, "unicon.log"),
    )
    try:
        ops = device.learn(feature)
    finally:
        device.destroy()
    return {
        "info": _json_safe(ops.info),
        "_exclude": _json_safe(list(ops.exclude or [])),
    }


def main() -> int:
    request = json.load(sys.stdin)
    try:
        payload = learn(
            request["os"],
            request["feature"],
            request["commands"],
            request.get("workdir"),
        )
    except Exception as exc:  # noqa: BLE001 - reported to the caller, never raised
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}"}))
        return 0
    print(json.dumps({"ok": True, "payload": payload}))
    return 0


if __name__ == "__main__":
    # Genie and Unicon log to stdout; keep our JSON line last and parse only that line.
    sys.exit(main())
