"""Command runner and device-config retrieval for Cisco Catalyst Center.

Command runner is asynchronous: submit ``read-request`` -> poll the task until its
``progress`` carries a ``fileId`` -> download that file. Catalyst Center only accepts
read-only (``show``-class) commands here, so this service exposes no write path.

Response shapes are spec-derived and not yet verified against a live controller
(see doc/CATALYST_CENTER_API_DIFF.md, open items).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from models.catalyst_center import CatalystCenterCommandResult, CatalystCenterCommandStatus
from services.catalyst_center.client import CatalystCenterService
from services.catalyst_center.common.exceptions import (
    CatalystCenterTaskError,
    CatalystCenterValidationError,
)
from services.catalyst_center.credentials import CatalystCenterCredentials
from services.catalyst_center.device_service import DEVICES_PATH, safe_device_id

logger = logging.getLogger(__name__)

READ_REQUEST_PATH = "/dna/intent/api/v1/network-device-poller/cli/read-request"
TASK_PATH = "/dna/intent/api/v1/task"
FILE_PATH = "/dna/intent/api/v1/file"

DEFAULT_COMMAND_TIMEOUT = 300
_MAX_COMMAND_TIMEOUT = 3600
_REQUEST_NAME = "auxilium-manus"
_MAX_FAILURE_REASON_CHARS = 200

_STATUS_BY_KEY = {
    "SUCCESS": CatalystCenterCommandStatus.SUCCESS,
    "FAILURE": CatalystCenterCommandStatus.FAILURE,
    "BLOCKLISTED": CatalystCenterCommandStatus.BLOCKLISTED,
}


def _opaque_id(value: Any, what: str) -> str:
    """Validate a controller-issued id before it is interpolated into a path."""
    try:
        return safe_device_id(value)
    except CatalystCenterValidationError as exc:
        raise CatalystCenterTaskError(f"Catalyst Center returned an invalid {what}") from exc


class CatalystCenterCommandService:
    def __init__(
        self,
        client: CatalystCenterService,
        credentials: CatalystCenterCredentials,
        *,
        poll_interval: float = 2.0,
        max_polls: int = 150,
    ) -> None:
        self._client = client
        self._credentials = credentials
        self._poll_interval = poll_interval
        self._max_polls = max_polls

    async def run_commands(
        self,
        device_ids: list[str],
        commands: list[str],
        *,
        timeout: int = DEFAULT_COMMAND_TIMEOUT,
    ) -> tuple[CatalystCenterCommandResult, ...]:
        body = self._build_request(device_ids, commands, timeout)
        submitted = await self._client.request(
            self._credentials, "POST", READ_REQUEST_PATH, json=body
        )
        task_id = _opaque_id(_nested(submitted, "response", "taskId"), "task id")
        file_id = await self._wait_for_file_id(task_id)
        payload = await self._client.request(self._credentials, "GET", f"{FILE_PATH}/{file_id}")
        return self._parse_results(payload)

    async def get_device_config(self, device_id: str) -> str:
        payload = await self._client.request(
            self._credentials, "GET", f"{DEVICES_PATH}/{safe_device_id(device_id)}/config"
        )
        config = payload.get("response") if isinstance(payload, dict) else None
        if not isinstance(config, str):
            raise CatalystCenterValidationError("Catalyst Center device config was not text")
        return config

    @staticmethod
    def _build_request(device_ids: list[str], commands: list[str], timeout: int) -> dict[str, Any]:
        if not device_ids:
            raise CatalystCenterValidationError("At least one device is required")
        cleaned = [command.strip() for command in commands if command and command.strip()]
        if not cleaned or len(cleaned) != len(commands):
            raise CatalystCenterValidationError("Commands must be non-empty")
        if not 1 <= timeout <= _MAX_COMMAND_TIMEOUT:
            raise CatalystCenterValidationError(
                f"Command timeout must be between 1 and {_MAX_COMMAND_TIMEOUT} seconds"
            )
        return {
            "name": _REQUEST_NAME,
            "commands": cleaned,
            "deviceUuids": [safe_device_id(device_id) for device_id in device_ids],
            "timeout": timeout,
        }

    async def _wait_for_file_id(self, task_id: str) -> str:
        for _ in range(self._max_polls):
            payload = await self._client.request(self._credentials, "GET", f"{TASK_PATH}/{task_id}")
            task = payload.get("response") if isinstance(payload, dict) else None
            if not isinstance(task, dict):
                raise CatalystCenterTaskError("Catalyst Center task response was not valid")
            if task.get("isError"):
                reason = str(task.get("failureReason") or "unknown reason")
                raise CatalystCenterTaskError(
                    f"Catalyst Center command task failed: {reason[:_MAX_FAILURE_REASON_CHARS]}"
                )
            file_id = _file_id_from_progress(task.get("progress"))
            if file_id is not None:
                return _opaque_id(file_id, "file id")
            await asyncio.sleep(self._poll_interval)
        raise CatalystCenterTaskError("Catalyst Center command task did not finish in time")

    @staticmethod
    def _parse_results(payload: Any) -> tuple[CatalystCenterCommandResult, ...]:
        if not isinstance(payload, list):
            raise CatalystCenterTaskError("Catalyst Center command output was not a list")
        results: list[CatalystCenterCommandResult] = []
        for entry in payload:
            device_id = entry.get("deviceUuid") if isinstance(entry, dict) else None
            responses = entry.get("commandResponses") if isinstance(entry, dict) else None
            if not isinstance(device_id, str) or not isinstance(responses, dict):
                continue
            for key, status in _STATUS_BY_KEY.items():
                outputs = responses.get(key)
                if not isinstance(outputs, dict):
                    continue
                results.extend(
                    CatalystCenterCommandResult(
                        device_id=device_id, command=command, status=status, output=str(output)
                    )
                    for command, output in outputs.items()
                )
        return tuple(results)


def _file_id_from_progress(progress: Any) -> str | None:
    if not isinstance(progress, str):
        return None
    try:
        decoded = json.loads(progress)
    except ValueError:
        return None
    file_id = decoded.get("fileId") if isinstance(decoded, dict) else None
    return file_id if isinstance(file_id, str) and file_id else None


def _nested(payload: Any, *keys: str) -> Any:
    current = payload
    for key in keys:
        current = current.get(key) if isinstance(current, dict) else None
    return current
