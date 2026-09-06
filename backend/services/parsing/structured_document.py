"""Parse a text blob as YAML or JSON into a Python object.

One shared parser for every "read a structured file/paste" feature — the
``read-from-file`` workflow step and the template editor's
``POST /templates/parse-structured`` endpoint both call this so that
format detection and error wording live in exactly one place.
"""

from __future__ import annotations

import json
import logging
from pathlib import PurePosixPath
from typing import Any

import yaml

logger = logging.getLogger(__name__)

FORMATS = frozenset({"yaml", "json", "auto"})

_JSON_EXTENSIONS = frozenset({".json"})
_YAML_EXTENSIONS = frozenset({".yaml", ".yml"})


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc


def _parse_yaml(text: str) -> Any:
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML: {exc}") from exc


def _format_from_filename(filename: str | None) -> str | None:
    if not filename:
        return None
    suffix = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    if suffix in _JSON_EXTENSIONS:
        return "json"
    if suffix in _YAML_EXTENSIONS:
        return "yaml"
    return None


def parse_structured_document(
    text: str, *, fmt: str = "auto", filename: str | None = None
) -> Any:
    """Parse *text* as YAML or JSON.

    ``fmt``:
      * ``"json"`` — strict ``json.loads``.
      * ``"yaml"`` — ``yaml.safe_load`` (also accepts JSON, since JSON is a
        subset of YAML).
      * ``"auto"`` (default) — pick by *filename* extension when it is
        ``.json`` / ``.yaml`` / ``.yml``; otherwise try JSON first (more
        precise errors) then fall back to YAML.

    Raises ``ValueError`` with a human-readable message on any parse failure.
    """
    normalized = str(fmt or "auto").strip().lower()
    if normalized not in FORMATS:
        raise ValueError(f"format must be one of {sorted(FORMATS)}")

    if normalized == "json":
        return _parse_json(text)
    if normalized == "yaml":
        return _parse_yaml(text)

    detected = _format_from_filename(filename)
    if detected == "json":
        return _parse_json(text)
    if detected == "yaml":
        return _parse_yaml(text)

    # No usable extension: try strict JSON first for its precise errors, then YAML.
    try:
        return _parse_json(text)
    except ValueError:
        return _parse_yaml(text)
