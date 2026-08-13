"""POST /v1/diff -- Genie-native diff of two already-learned snapshot payloads.

Pure in-process computation, no subprocess/testbed/device I/O -- unlike
/v1/jobs this never touches JobRunner. Callers pass the "data" payload of one
Genie feature from two previously captured pyats_snapshot artifacts (see
get-pyats-snapshot); this endpoint runs genie.utils.diff.Diff on them.

UNVERIFIED ASSUMPTION (see doc/PYATS_INTEGRATION.md "Open items"): the shim's
learn operation stores ops.to_dict(), while Genie's documented Diff usage is
Diff(a.info, b.info). Test fixture evidence in tests/test_generic_script.py
suggests to_dict() wraps .info under an "info" key, but this has not been
confirmed against a real pyATS install. _unwrap() below extracts "info" when
present and otherwise assumes to_dict() is already .info-equivalent.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import require_bearer_token

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_bearer_token)])


class DiffRequest(BaseModel):
    snapshot_a: dict[str, Any]
    snapshot_b: dict[str, Any]


class DiffResponse(BaseModel):
    identical: bool
    diff: str


def _unwrap(snapshot: dict[str, Any]) -> Any:
    if isinstance(snapshot, dict) and "info" in snapshot:
        return snapshot["info"]
    return snapshot


def _compute_diff(snapshot_a: dict[str, Any], snapshot_b: dict[str, Any]) -> tuple[bool, str]:
    from genie.utils.diff import Diff  # lazy import -- genie only exists inside the container

    diff = Diff(_unwrap(snapshot_a), _unwrap(snapshot_b))
    diff.findDiff()
    text = str(diff)
    return (not text.strip()), text


@router.post("/v1/diff", response_model=DiffResponse)
async def diff_snapshots(body: DiffRequest) -> DiffResponse:
    try:
        identical, diff_text = _compute_diff(body.snapshot_a, body.snapshot_b)
    except Exception as exc:  # noqa: BLE001 - malformed/incompatible input, not a server bug
        logger.warning("diff computation failed: %s", exc)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Genie diff failed: {exc}") from exc

    logger.info("diff computed identical=%s", identical)
    return DiffResponse(identical=identical, diff=diff_text)
