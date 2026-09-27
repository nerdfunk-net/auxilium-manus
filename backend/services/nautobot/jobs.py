"""Nautobot Job REST operations — list jobs, fetch a job's variable schema, run a job, and
check a job result's status."""

from __future__ import annotations

from typing import Any

from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient


class NautobotJobsService:
    """Thin wrapper over Nautobot's ``/api/extras/jobs/`` REST surface."""

    def __init__(self, client: CredentialsBoundNautobotClient) -> None:
        self._client = client

    async def list_jobs(self, *, enabled_only: bool = True) -> list[dict[str, Any]]:
        query = "enabled=true&limit=1000" if enabled_only else "limit=1000"
        response = await self._client.rest_request(f"extras/jobs/?{query}")
        results = response.get("results") if isinstance(response, dict) else response
        return list(results) if isinstance(results, list) else []

    async def get_job_variables(self, job_id: str) -> list[dict[str, Any]]:
        response = await self._client.rest_request(f"extras/jobs/{job_id}/variables/")
        if isinstance(response, list):
            return response
        results = response.get("results") if isinstance(response, dict) else None
        return list(results) if isinstance(results, list) else []

    async def run_job(
        self,
        job_id: str,
        *,
        data: dict[str, Any],
        task_queue: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"data": data}
        if task_queue:
            payload["task_queue"] = task_queue
        return await self._client.rest_request(
            f"extras/jobs/{job_id}/run/", method="POST", data=payload
        )

    async def get_job_result(self, job_result_id: str) -> dict[str, Any]:
        return await self._client.rest_request(f"extras/job-results/{job_result_id}/")
