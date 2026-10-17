"""Operator limits on the AI assistant (``AI_ASSISTANT_ENABLED``, ``AI_ALLOWED_PROVIDERS``,
``AI_ALLOWED_DATA``). Pure functions: a user's own switches can only narrow what the operator
allows, never widen it.
"""

from __future__ import annotations

from collections.abc import Collection

# Per-user share flag -> operator data token (the six data classes of AI_ASSISTANT.md §4.1).
DATA_TOKEN_FOR_FLAG: dict[str, str] = {
    "share_inventory_data": "inventory",
    "share_device_addresses": "addresses",
    "share_custom_fields": "custom_fields",
    "share_config_context": "config_context",
    "share_content_data": "content",
    "share_report_data": "report",
}


def provider_allowed(provider: str, allowed_providers: Collection[str]) -> bool:
    return provider in allowed_providers


def effective_share(flag: str, user_value: bool, allowed_data: Collection[str]) -> bool:
    """The user's switch ANDed with the operator's data set."""
    return bool(user_value) and DATA_TOKEN_FOR_FLAG[flag] in allowed_data
