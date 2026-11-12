"""Configuration parsing for the discover-network step."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.network.netmiko.connection import DEFAULT_READ_TIMEOUT, RetryPolicy
from workflow_steps.common.read_timeout import parse_read_timeout
from workflow_steps.common.retry_config import parse_retry_backoff_seconds
from workflow_steps.common.step_flags import parse_bool_flag, parse_int_flag
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


def _bounded(config: dict[str, Any], key: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return parse_int_flag(config, key, default=default, minimum=minimum, maximum=maximum)
    except ValueError as exc:
        raise ValueError(f"{STEP_ID}: {exc}") from exc


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
        max_devices=_bounded(config, "max_devices", 50, 1, 500),
        max_depth=_bounded(config, "max_depth", 5, 1, 20),
        concurrency=_bounded(config, "concurrency", 5, 1, 20),
        network_driver_override=str(config.get("network_driver_override") or "").strip() or None,
        read_timeout=parse_read_timeout(config, step_id=STEP_ID, default=DEFAULT_READ_TIMEOUT),
        dry_run=parse_bool_flag(config, "dry_run"),
        retry=parse_retry_backoff_seconds(config, step_id=STEP_ID),
    )
