"""Opt-in data sharing (doc/ai_integration/AI_ASSISTANT.md §4).

Anything derived from devices or runs reaches the model only if the user switched the matching
class on. The check lives in the tool layer, not the UI: a tool asks the policy before it puts a
class B/C value in its result, and substitutes a ``not_shared`` marker otherwise so the model can
tell the user what to enable instead of failing silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class DataClass(StrEnum):
    INVENTORY = "inventory_data"  # class B: device names, attributes, inventories
    CONTENT = "content_data"  # class C: command output, configs, errors, run logs


_SETTING_FOR: dict[DataClass, str] = {
    DataClass.INVENTORY: "Share inventory data",
    DataClass.CONTENT: "Share content data",
}


@dataclass(frozen=True)
class SharingPolicy:
    """What the calling user has opted in to. The default shares nothing."""

    inventory: bool = False
    content: bool = False

    def allows(self, data_class: DataClass) -> bool:
        return self.inventory if data_class is DataClass.INVENTORY else self.content


def not_shared_marker(data_class: DataClass) -> dict[str, str]:
    """A value to put where withheld data would have been."""
    return {
        "not_shared": data_class.value,
        "message": (
            f"The user has not enabled '{_SETTING_FOR[data_class]}' in the assistant settings. "
            "Tell them to enable it if you need this, or answer without it."
        ),
    }


def gated(policy: SharingPolicy, data_class: DataClass, value: Any) -> Any:
    """``value`` if the class is shared, else the not-shared marker."""
    return value if policy.allows(data_class) else not_shared_marker(data_class)


class DeviceLabeler:
    """Stable per-request device labels: real names when inventory data is shared, else
    ``device-1``, ``device-2`` ... so a failure can still be discussed per device."""

    def __init__(self, policy: SharingPolicy) -> None:
        self._share = policy.inventory
        self._labels: dict[str, str] = {}

    def seed(self, names: set[str]) -> None:
        """Number ``names`` in sorted order (names not yet labeled), independent of call order."""
        for name in sorted(names):
            self.label(name)

    def label(self, name: str) -> str:
        if self._share:
            return name
        return self._labels.setdefault(name, f"device-{len(self._labels) + 1}")

    def matches(self, name: str, wanted: str) -> bool:
        return wanted in (name, self.label(name)) if self._share else wanted == self.label(name)
