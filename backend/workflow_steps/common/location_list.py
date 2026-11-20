"""Parse a list of location names or UUIDs typed in a step configuration."""

from __future__ import annotations

import csv


def split_locations(text: str) -> list[str]:
    """Location entries separated by commas or new lines; a name with a comma is "quoted"."""
    parts: list[str] = []
    for row in csv.reader(text.splitlines(), skipinitialspace=True):
        parts.extend(part.strip() for part in row if part.strip())
    return parts
