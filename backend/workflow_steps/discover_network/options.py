"""Configuration parsing for the discover-network step."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.network.netmiko.connection import DEFAULT_READ_TIMEOUT, RetryPolicy
from workflow_steps.common.read_timeout import parse_read_timeout
from workflow_steps.common.retry_config import parse_retry_backoff_seconds
from workflow_steps.common.step_flags import parse_bool_flag, parse_int_flag
from workflow_steps.discover_network.config import get_config
from workflow_steps.discover_network.scope import STEP_ID, Prefixes, parse_prefixes

__all__ = ["STEP_ID", "DiscoverOptions", "parse_options"]


@dataclass(frozen=True)
class DiscoverOptions:
    follow_neighbors: bool
    prefixes: Prefixes
    follow_only_infrastructure: bool
    max_devices: int
    max_depth: int
    concurrency: int
    network_driver_override: str | None
    read_timeout: int
    dry_run: bool
    retry: RetryPolicy
    resolve_management_ip: bool
    nautobot_source_id: str | None


def parse_options(config: dict[str, Any]) -> DiscoverOptions:
    follow = parse_bool_flag(config, "follow_neighbors")
    prefixes = parse_prefixes(config.get("permitted_prefixes"))
    if follow and not prefixes:
        raise ValueError(
            f"{STEP_ID}: permitted_prefixes must list at least one CIDR prefix "
            "when follow_neighbors is on"
        )
    return DiscoverOptions(
        follow_neighbors=follow,
        prefixes=prefixes,
        follow_only_infrastructure=parse_bool_flag(
            config, "follow_only_infrastructure", default=True
        ),
        max_devices=parse_int_flag(
            config,
            "max_devices",
            default=get_config()["max_devices"],
            minimum=1,
            maximum=500,
            step_id=STEP_ID,
        ),
        max_depth=parse_int_flag(
            config,
            "max_depth",
            default=get_config()["max_depth"],
            minimum=1,
            maximum=20,
            step_id=STEP_ID,
        ),
        concurrency=parse_int_flag(
            config,
            "concurrency",
            default=get_config()["concurrency"],
            minimum=1,
            maximum=20,
            step_id=STEP_ID,
        ),
        network_driver_override=str(config.get("network_driver_override") or "").strip() or None,
        read_timeout=parse_read_timeout(config, step_id=STEP_ID, default=DEFAULT_READ_TIMEOUT),
        dry_run=parse_bool_flag(config, "dry_run"),
        retry=parse_retry_backoff_seconds(config, step_id=STEP_ID),
        resolve_management_ip=parse_bool_flag(config, "resolve_management_ip", default=True),
        nautobot_source_id=str(config.get("nautobot_source_id") or "").strip() or None,
    )
