"""pyATS shim batching, client side: chunk a group of devices, call ``run_job()`` once per
chunk under the shim's own concurrency limit, and read a per-device shim result.

The step glue (resolving the pyATS sources of the devices, validating them and grouping them by
source) is ``workflow_steps/common/pyats_batch.py``; this module knows nothing about steps.

Device connects and command executions run **sequentially** inside a single shim job (confirmed
in ``pyats-shim/app/job_scripts/generic_script.py``: ``CommonSetup.connect_devices`` and
``RunRequestedOperation.run_commands`` both loop over the testbed devices, one at a time).
Batching therefore trades "N concurrent pyATS subprocesses" for "fewer subprocesses, each doing
sequential per-device work": the chunk size must stay conservative, and the outer job timeout
scales with the chunk size to avoid false timeouts on otherwise-healthy chunks. See
doc/PYATS_INTEGRATION.md's "Get & Parse Config" and "Open items" sections.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from models.failure import FailureInfo
from services.pyats.common.exceptions import PyATSAPIError, PyATSValidationError

if TYPE_CHECKING:
    from services.pyats.client import PyATSShimService
    from services.pyats.credentials import PyATSCredentials

DEFAULT_CHUNK_SIZE = 5
BASE_TIMEOUT_SECONDS = 60.0
PER_DEVICE_TIMEOUT_SECONDS = 90.0


def _chunk(
    items: list[tuple[str, dict[str, Any]]], chunk_size: int
) -> list[list[tuple[str, dict[str, Any]]]]:
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


# A device-level error is whatever the device printed; it keeps its text, capped, because the
# operator needs it ("Authentication failed") but a banner or a dump must not fill the stored run.
MAX_SHIM_TEXT = 300
_GENERIC_DEVICE_ERROR = "pyATS shim reported failure for this device"
_DEVICE_LEVEL_FAILURE = FailureInfo(phase="command", kind="command_error")


def cap_shim_text(text: str) -> str:
    """Text the shim produced (a device's exception chain, a 400 detail) as it may be stored or
    shown: at most ``MAX_SHIM_TEXT`` characters plus an ellipsis (R4-01, R9-01)."""
    return f"{text[:MAX_SHIM_TEXT]}…" if len(text) > MAX_SHIM_TEXT else text


def shim_device_failure(result: dict[str, Any] | None) -> tuple[str, FailureInfo]:
    """The message and the classification of a failed per-device shim result.

    A chunk-level failure carries the classification of its ``PyATSError`` (``run_batched``); a
    device-level error from the shim does not, and is a generic ``command_error``.
    """
    carried = (result or {}).get("failure")
    text = cap_shim_text(str((result or {}).get("error") or "").strip() or _GENERIC_DEVICE_ERROR)
    return text, carried if isinstance(carried, FailureInfo) else _DEVICE_LEVEL_FAILURE


async def shim_concurrency(shim: Any, credentials: Any, *, default: int = 4) -> int:
    """How many jobs the shim runs at once (its /health/pyats limit), so a step never makes it
    queue work for a client that may have given up (C4-01, C4R-04)."""
    try:
        limits = await shim.limits(credentials)
        return max(1, int(limits.max_concurrent_jobs))
    except Exception:  # noqa: BLE001 - advisory only
        return default


async def run_batched(
    *,
    shim: PyATSShimService,
    credentials: PyATSCredentials,
    operation: str,
    commands: list[str],
    device_group: list[tuple[str, dict[str, Any]]],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> dict[str, dict[str, Any]]:
    """Run one ``operation`` against every device in ``device_group``, chunked.

    Chunks call the shim concurrently. A chunk-level failure (network error,
    timeout, or a validation rejection) fails every device in that chunk only
    -- other chunks are unaffected. Returns a flat ``device_id -> shim result``
    dict merged across all chunks, matching the
    ``response["results"][device_id]`` shape callers already consume.
    """
    if not device_group:
        return {}

    gate = asyncio.Semaphore(await shim_concurrency(shim, credentials))

    async def _run_chunk(
        chunk: list[tuple[str, dict[str, Any]]],
    ) -> dict[str, dict[str, Any]]:
        async with gate:
            return await _run_chunk_unguarded(chunk)

    async def _run_chunk_unguarded(
        chunk: list[tuple[str, dict[str, Any]]],
    ) -> dict[str, dict[str, Any]]:
        shim_devices = [shim_device for _device_id, shim_device in chunk]
        timeout_seconds = BASE_TIMEOUT_SECONDS + PER_DEVICE_TIMEOUT_SECONDS * len(chunk)
        try:
            response = await shim.run_job(
                credentials,
                operation=operation,
                devices=shim_devices,
                commands=commands,
                timeout_seconds=timeout_seconds,
            )
            return dict(response.get("results") or {})
        except (PyATSAPIError, PyATSValidationError) as exc:
            error, failure = str(exc), exc.failure
        except Exception as exc:
            # A malformed answer (a proxy page instead of JSON) or any other unexpected error
            # fails this chunk only, and only its class name is kept (W7-03).
            error = type(exc).__name__
            failure = FailureInfo(
                phase="internal", kind="internal_error", exception_type=type(exc).__name__
            )
        return {
            device_id: {"success": False, "error": error, "failure": failure, "commands": {}}
            for device_id, _shim_device in chunk
        }

    chunk_results = await asyncio.gather(
        *[_run_chunk(chunk) for chunk in _chunk(device_group, chunk_size)]
    )
    merged: dict[str, dict[str, Any]] = {}
    for result in chunk_results:
        merged.update(result)
    return merged
