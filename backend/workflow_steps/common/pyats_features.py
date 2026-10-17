"""Shared parsing for the ``features`` config value used by pyATS steps.

Both ``get-pyats-snapshot`` and ``compare-pyats-snapshot`` take a list of Genie
feature names in their plugin config. This helper turns that raw config value
into an ordered, de-duplicated list of non-empty strings, raising ``ValueError``
on bad input so the calling executor surfaces it as a configuration error.
"""

from __future__ import annotations


def parse_feature_list(raw: object, *, step_id: str) -> list[str]:
    """Validate a ``features`` config value.

    Returns the feature names with surrounding whitespace stripped, duplicates
    removed, and original order preserved. Raises ``ValueError`` when ``raw`` is
    not a non-empty list or contains a blank entry.
    """
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            f"{step_id}: features must be a non-empty list of Genie feature names"
        )
    features: list[str] = []
    seen: set[str] = set()
    for item in raw:
        name = str(item).strip()
        if not name:
            raise ValueError(f"{step_id}: features entries must be non-empty strings")
        if name not in seen:
            seen.add(name)
            features.append(name)
    return features
