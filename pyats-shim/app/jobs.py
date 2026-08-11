"""POST /v1/jobs -- run a pyATS execute/parse job against a batch of devices.

All devices in one request share a single job/subprocess invocation (one
testbed, one AEtest run) so parallel workflow steps don't each pay pyATS's
easypy startup cost per device.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.auth import require_bearer_token
from app.job_runner import JobRunner, JobTimeoutError
from app.testbed_builder import TestbedBuildError

router = APIRouter(dependencies=[Depends(require_bearer_token)])


class DeviceRequest(BaseModel):
    name: str = Field(..., min_length=1)
    host: str = Field(..., min_length=1)
    os: str = Field(..., min_length=1)
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    platform: str | None = None
    port: int | None = None
    protocol: str = "ssh"


class JobRequest(BaseModel):
    operation: Literal["execute", "parse"]
    devices: list[DeviceRequest] = Field(..., min_length=1)
    commands: list[str] = Field(..., min_length=1)
    timeout_seconds: float | None = Field(default=None, ge=1, le=600)


class CommandResult(BaseModel):
    raw: str | None = None
    parsed: dict | list | None = None
    error: str | None = None


class DeviceResult(BaseModel):
    success: bool
    error: str | None = None
    commands: dict[str, CommandResult] = Field(default_factory=dict)


class JobResponse(BaseModel):
    results: dict[str, DeviceResult]


def get_job_runner(request: Request) -> JobRunner:
    return request.app.state.job_runner


@router.post("/v1/jobs", response_model=JobResponse)
async def run_job(
    body: JobRequest,
    job_runner: JobRunner = Depends(get_job_runner),
) -> JobResponse:
    try:
        raw_results = await job_runner.run(
            operation=body.operation,
            devices=[device.model_dump() for device in body.devices],
            commands=body.commands,
            timeout_seconds=body.timeout_seconds,
        )
    except TestbedBuildError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except JobTimeoutError as exc:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, str(exc)) from exc
    return JobResponse(results=raw_results)
