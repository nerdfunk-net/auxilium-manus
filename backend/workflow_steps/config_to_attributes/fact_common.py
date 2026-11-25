"""Helpers shared by the two fact-dict mappers (Catalyst Center and ACI)."""

from __future__ import annotations

from typing import Any

DEFAULT_MANUFACTURER = "Cisco"


def fact_payload(entry: dict[str, Any], fact: str) -> Any:
    """The ``parsed`` payload of one fact of a ``{"<fact>": {"parsed", "error"}}`` entry."""
    fact_entry = entry.get(fact) if isinstance(entry, dict) else None
    return fact_entry.get("parsed") if isinstance(fact_entry, dict) else None


def clean_text(value: Any) -> str | None:
    """``value`` as stripped text, or ``None`` when it is missing or blank."""
    stripped = str(value).strip() if value is not None else ""
    return stripped or None
