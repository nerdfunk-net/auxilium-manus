"""Catalyst Center health for Ask the Net (doc/AI_TOOL_CHAIN.md §58).

Two pure reads, as the calling user: the health of one device (``GET /device-detail``, the same
fact as the step ``get-catalyst-center-health``) and the health of the sites
(``GET /site-health``). Scores are the controller's own numbers, passed on as reported.

Data sharing, fail closed: both need the inventory switch, checked before any request. A device
lookup by management IP or serial also needs the addresses switch (as in §42). Upstream error
text never reaches the model.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from services.ai_assistant.data_sharing import DataClass, not_shared_marker
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.catalyst_center_tools import (
    _BAD_LOOKUP,
    _SOURCE_ERRORS,
    FindDeviceInput,
    _all_failed,
    _ambiguous,
    _failure_sentence,
    _finish,
    _gate,
    _not_found,
    _search,
    _sources_or_error,
)
from services.catalyst_center.common.exceptions import (
    CatalystCenterNotFoundError,
    CatalystCenterValidationError,
)

DEFAULT_SITES = 25
MAX_SITES = 50
_SITE_NOT_AVAILABLE = "This Catalyst Center does not offer the site health API."

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


def _iso(epoch_ms: int | None) -> str | None:
    """A controller timestamp (milliseconds since the epoch) as UTC text; ``None`` if unusable."""
    if epoch_ms is None or epoch_ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(epoch_ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OverflowError, OSError, ValueError:
        return None


# -- get_catalyst_center_device_health -------------------------------------------------------


async def _device_health(ctx: ToolContext, args: FindDeviceInput) -> ToolOutput:
    if (blocked := _gate(ctx, args)) is not None:
        return blocked
    sources = await _sources_or_error(ctx)
    if isinstance(sources, ToolOutput):
        return sources
    try:
        found = await _search(sources, args)
    except CatalystCenterValidationError:
        return _BAD_LOOKUP
    if (failed := _all_failed(found)) is not None:
        return failed
    if not found.matches:
        payload: dict[str, Any] = {"found": False, "message": _not_found(args)}
        if found.errors:
            payload["source_errors"] = found.errors
        return _finish(ctx, payload)
    if len(found.matches) > 1:
        return _ambiguous(found)
    source, device = found.matches[0]
    payload = {
        "found": True,
        "source_id": source.source_id,
        "device_id": device.id,
        "hostname": device.hostname,
    }
    try:
        if source.health is None:  # pragma: no cover - the reader always builds it
            raise CatalystCenterNotFoundError()
        health = await source.health.get_device_health(device.id)
    except _SOURCE_ERRORS as exc:
        payload["health"] = {"error": _failure_sentence(exc)}
        return _finish(ctx, payload)
    data = health.model_dump(exclude={"timestamp", "last_boot_time"}, exclude_none=True)
    data["collected_at"] = _iso(health.timestamp)
    data["last_boot"] = _iso(health.last_boot_time)
    payload["health"] = {"data": {k: v for k, v in data.items() if v is not None}}
    return _finish(ctx, payload)


# -- list_catalyst_center_site_health --------------------------------------------------------


class SiteHealthInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_type: Literal["AREA", "BUILDING"] | None = Field(
        None, description="Only areas or only buildings (the controller reports no floors here)."
    )
    name_contains: Text | None = Field(
        None, description="Only sites whose name contains this text (any case)."
    )
    max_network_health: Annotated[float, Field(ge=0, le=100)] | None = Field(
        None,
        description="Only sites whose average network health is at or below this value "
        "(for 'which sites are unhealthy'). Sites with no score are left out.",
    )
    limit: Annotated[int, Field(ge=1, le=MAX_SITES)] = DEFAULT_SITES
    offset: Annotated[int, Field(ge=0, le=100_000)] = 0


def _site_row(row: Any) -> dict[str, Any]:
    return row.model_dump(exclude_none=True)


def _site_sort_key(row: Any) -> tuple[bool, float, str]:
    # Worst first; sites without a score last.
    score = row.network_health_average
    return (score is None, score if score is not None else 0.0, row.site_name.lower())


async def _site_health(ctx: ToolContext, args: SiteHealthInput) -> ToolOutput:
    if not ctx.sharing.allows(DataClass.INVENTORY):
        return ToolOutput(json.dumps(not_shared_marker(DataClass.INVENTORY), indent=1))
    sources = await _sources_or_error(ctx)
    if isinstance(sources, ToolOutput):
        return sources
    needle = args.name_contains.lower() if args.name_contains else None
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for source in sources:
        try:
            if source.site_health is None:  # pragma: no cover - the reader always builds it
                raise CatalystCenterNotFoundError()
            rows = await source.site_health.list_site_health(site_type=args.site_type)
        except CatalystCenterNotFoundError:
            errors.append({"source_id": source.source_id, "error": _SITE_NOT_AVAILABLE})
            continue
        except _SOURCE_ERRORS as exc:
            errors.append({"source_id": source.source_id, "error": _failure_sentence(exc)})
            continue
        kept = [
            r
            for r in rows
            if (needle is None or needle in r.site_name.lower())
            and (
                args.max_network_health is None
                or (
                    r.network_health_average is not None
                    and r.network_health_average <= args.max_network_health
                )
            )
        ]
        kept.sort(key=_site_sort_key)
        results.append(
            {
                "source_id": source.source_id,
                "total": len(kept),
                "has_more": args.offset + args.limit < len(kept),
                "sites": [_site_row(r) for r in kept[args.offset : args.offset + args.limit]],
            }
        )
    if not results:
        detail = "; ".join(f"source '{e['source_id']}': {e['error']}" for e in errors)
        return ToolOutput(f"Catalyst Center could not be read. {detail}", is_error=True)
    payload: dict[str, Any] = {"sources": results}
    if errors:
        payload["source_errors"] = errors
    return _finish(ctx, payload)


def build_catalyst_center_health_tools() -> tuple[Tool, ...]:
    async def device(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _device_health(ctx, args)

    async def sites(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _site_health(ctx, args)

    return (
        Tool(
            "get_catalyst_center_device_health",
            "Health of one device from Cisco Catalyst Center: overall health score, CPU and "
            "memory with their scores, communication state, HA status, maintenance mode, last "
            "boot. Look the device up by name, management IP or serial number (several matches "
            "are an error that lists them). The scores are the controller's own numbers (device "
            "scores usually 0-10, higher is better): report them as given and do not invent a "
            "threshold. It is the controller's last collected view (see collected_at), not a "
            "live check. Needs the inventory data switch; lookup by IP or serial also needs the "
            "addresses switch.",
            FindDeviceInput,
            device,
        ),
        Tool(
            "list_catalyst_center_site_health",
            "Health of the Catalyst Center sites: average network health, number of devices, "
            "health per device role (access, core, distribution, router, wireless) and client "
            "health, worst sites first. Use it for 'how healthy are the sites' and 'which sites "
            "are unhealthy' (max_network_health). Narrow with site_type or name_contains; page "
            "with limit/offset. Scores are the controller's own (site averages usually 0-100): "
            "report them as given. Controllers without the site health API answer with a fixed "
            "sentence. Needs the inventory data switch.",
            SiteHealthInput,
            sites,
        ),
    )
