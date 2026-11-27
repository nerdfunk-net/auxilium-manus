"""Configuration parsing for the collect-client-data step."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.network.netmiko.connection import DEFAULT_READ_TIMEOUT, RetryPolicy
from workflow_steps.collect_client_data.config import get_config
from workflow_steps.common.read_timeout import parse_read_timeout
from workflow_steps.common.retry_config import parse_retry_backoff_seconds
from workflow_steps.common.step_flags import (
    parse_bool_flag,
    parse_float_flag,
    parse_int_flag,
)

STEP_ID = "collect-client-data"

_DEFAULT_DNS_TIMEOUT = 2.0
_MIN_DNS_TIMEOUT = 0.1
_MAX_DNS_TIMEOUT = 30.0
_MAX_DNS_CONCURRENCY = 100


@dataclass(frozen=True)
class CollectOptions:
    collect_ip_address: bool
    collect_mac_address: bool
    collect_vrfs: bool
    collect_hostname: bool
    collect_neighbors: bool
    dns_timeout_seconds: float
    dns_concurrency: int
    network_driver_override: str | None
    read_timeout: int
    dry_run: bool
    retry: RetryPolicy


def parse_options(config: dict[str, Any]) -> CollectOptions:
    collect_ip = parse_bool_flag(config, "collect_ip_address", default=True)
    collect_mac = parse_bool_flag(config, "collect_mac_address", default=True)
    collect_hostname = parse_bool_flag(config, "collect_hostname")
    collect_neighbors = parse_bool_flag(config, "collect_neighbors")
    if not (collect_ip or collect_mac or collect_neighbors):
        raise ValueError(
            f"{STEP_ID}: collect_ip_address, collect_mac_address or collect_neighbors "
            "must be enabled"
        )
    if collect_hostname and not collect_ip:
        raise ValueError(
            f"{STEP_ID}: collect_hostname needs collect_ip_address (it resolves the ARP addresses)"
        )
    concurrency = parse_int_flag(
        config,
        "dns_concurrency",
        default=get_config()["dns_concurrency"],
        minimum=1,
        maximum=_MAX_DNS_CONCURRENCY,
        step_id=STEP_ID,
    )
    return CollectOptions(
        collect_ip_address=collect_ip,
        collect_mac_address=collect_mac,
        # Per-VRF ARP only makes sense when ARP is collected.
        collect_vrfs=collect_ip and parse_bool_flag(config, "collect_vrfs", default=True),
        collect_hostname=collect_hostname,
        collect_neighbors=collect_neighbors,
        dns_timeout_seconds=parse_float_flag(
            config,
            "dns_timeout_seconds",
            default=_DEFAULT_DNS_TIMEOUT,
            minimum=_MIN_DNS_TIMEOUT,
            maximum=_MAX_DNS_TIMEOUT,
            step_id=STEP_ID,
        ),
        dns_concurrency=concurrency,
        network_driver_override=str(config.get("network_driver_override") or "").strip() or None,
        read_timeout=parse_read_timeout(config, step_id=STEP_ID, default=DEFAULT_READ_TIMEOUT),
        dry_run=parse_bool_flag(config, "dry_run"),
        retry=parse_retry_backoff_seconds(config, step_id=STEP_ID),
    )
