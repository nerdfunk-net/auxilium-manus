"""Shared fakes for the AI assistant tests."""

from __future__ import annotations

from types import SimpleNamespace


class FakeRepo:
    """In-memory stand-in for UserAiSettingsRepository (keyed by user id)."""

    def __init__(self) -> None:
        self.rows: dict[int, SimpleNamespace] = {}

    def get_by_user_id(self, user_id: int):
        return self.rows.get(user_id)

    def upsert(self, user_id: int, values):
        row = self.rows.get(user_id) or SimpleNamespace(
            user_id=user_id,
            enabled=False,
            provider="anthropic",
            model="",
            base_url=None,
            api_key_encrypted=None,
            share_inventory_data=False,
            share_device_addresses=False,
            share_custom_fields=False,
            share_config_context=False,
            share_content_data=False,
        )
        for key, value in values.items():
            setattr(row, key, value)
        self.rows[user_id] = row
        return row
