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

NOTE: genie.utils.diff.Diff does NOT ignore volatile/time-based keys (e.g.
"updated", "uptime", "last_change") by default -- it compares every key
literally unless an explicit `exclude` list is passed to its constructor.
Callers that want that noise ignored must pass `exclude` in the request body;
see compare-pyats-snapshot's `exclude_keys` config.

A learned Genie Ops object also carries its own per-feature volatile-field list as `_exclude` next
to `info`. Only the keys in `SNAPSHOT_NOISE_KEYS` (ages, timers, checksums, sequence numbers) are taken
from it. The rest of such a list is comparison policy, not noise: for ospf it also names `state`,
`dr_*`/`bdr_*`, `statistics` and the whole `lsas` subtree, so honouring it would report a neighbour
that falls back to INIT or a new LSA as "identical". The same list is read from the reference file,
which a writer of the reference store controls; a fixed allowlist keeps it from switching off a
comparison. Keys of a snapshot's list that are not applied come back in `not_applied`.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import require_bearer_token

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_bearer_token)])


# Fields that change on every read and mean nothing by themselves. Everything else a snapshot lists
# in `_exclude` is ignored unless the caller names it in `exclude`.
SNAPSHOT_NOISE_KEYS: frozenset[str] = frozenset(
    {
        "age",
        "uptime",
        "last_change",
        "last_state_change",
        "cksum",
        "checksum",
        "seq",
        "seq_num",
        "dead_timer",
        "hello_timer",
        "area_scope_lsa_cksum_sum",
    }
)
MAX_SNAPSHOT_EXCLUDES = 200


class DiffRequest(BaseModel):
    snapshot_a: dict[str, Any]
    snapshot_b: dict[str, Any]
    exclude: list[str] | None = None
    use_snapshot_excludes: bool = True


class DiffResponse(BaseModel):
    identical: bool
    diff: str
    excluded: list[str] = []
    not_applied: list[str] = []


def _unwrap(snapshot: dict[str, Any]) -> Any:
    if isinstance(snapshot, dict) and "info" in snapshot:
        return snapshot["info"]
    return snapshot


def _snapshot_excludes(snapshot: Any) -> list[str]:
    """The `_exclude` list a learned Ops payload carries, as strings (empty when absent)."""
    if not isinstance(snapshot, dict):
        return []
    raw = snapshot.get("_exclude")
    if not isinstance(raw, list):
        return []
    keys = [str(key).strip() for key in raw[:MAX_SNAPSHOT_EXCLUDES]]
    return [key for key in keys if key]


def snapshot_excludes(snapshot_a: Any, snapshot_b: Any) -> tuple[list[str], list[str]]:
    """The snapshots' `_exclude` keys split into (applied noise keys, kept compared)."""
    keys = list(dict.fromkeys(_snapshot_excludes(snapshot_a) + _snapshot_excludes(snapshot_b)))
    applied = [key for key in keys if key in SNAPSHOT_NOISE_KEYS]
    return applied, [key for key in keys if key not in SNAPSHOT_NOISE_KEYS]


def merged_excludes(
    snapshot_a: Any,
    snapshot_b: Any,
    *,
    exclude: list[str] | None = None,
    use_snapshot_excludes: bool = True,
) -> list[str]:
    """The caller's keys first, then those of both snapshots; each key once, in order."""
    keys = list(exclude or [])
    if use_snapshot_excludes:
        keys += snapshot_excludes(snapshot_a, snapshot_b)[0]
    return list(dict.fromkeys(keys))


def _compute_diff(
    snapshot_a: dict[str, Any],
    snapshot_b: dict[str, Any],
    *,
    exclude: list[str] | None = None,
    use_snapshot_excludes: bool = True,
) -> tuple[bool, str, list[str], list[str]]:
    from genie.utils.diff import Diff  # lazy import -- genie only exists inside the container

    excluded = merged_excludes(
        snapshot_a,
        snapshot_b,
        exclude=exclude,
        use_snapshot_excludes=use_snapshot_excludes,
    )
    diff_kwargs: dict[str, Any] = {}
    if excluded:
        diff_kwargs["exclude"] = excluded
    diff = Diff(_unwrap(snapshot_a), _unwrap(snapshot_b), **diff_kwargs)
    diff.findDiff()
    text = str(diff)
    not_applied = snapshot_excludes(snapshot_a, snapshot_b)[1] if use_snapshot_excludes else []
    return (not text.strip()), text, excluded, not_applied


@router.post("/v1/diff", response_model=DiffResponse)
async def diff_snapshots(body: DiffRequest) -> DiffResponse:
    try:
        identical, diff_text, excluded, not_applied = _compute_diff(
            body.snapshot_a,
            body.snapshot_b,
            exclude=body.exclude,
            use_snapshot_excludes=body.use_snapshot_excludes,
        )
    except Exception as exc:  # noqa: BLE001 - malformed/incompatible input, not a server bug
        logger.warning("diff computation failed: %s", exc)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Genie diff failed: {exc}") from exc

    logger.info("diff computed identical=%s", identical)
    return DiffResponse(
        identical=identical, diff=diff_text, excluded=excluded, not_applied=not_applied
    )
