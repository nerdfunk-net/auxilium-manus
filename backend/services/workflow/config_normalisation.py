"""Booleans in node configuration are real booleans (C12-01).

The editor stores real booleans, but a workflow imported from a file, patched by the AI apply
script or written by an API client may carry ``"true"`` / ``"false"`` strings. Nodes are normalised
where they enter (create / update) and where they leave (read), using the registry's
``data_type: boolean`` declarations, so every panel and every executor sees the same value.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import lru_cache
from typing import Any

from core.config import settings
from models.plugins import PluginDefinition
from repositories.plugin_repository import PluginRepository
from services.plugin_registry.plugin_registry_service import PluginRegistryService
from services.workflow_context.flags import parse_bool_flag

logger = logging.getLogger(__name__)

PluginLookup = Callable[[str], PluginDefinition | None]


@lru_cache(maxsize=1)
def _default_registry() -> PluginRegistryService:
    service = PluginRegistryService(PluginRepository(plugins_file=settings.plugins_file))
    service.load_registry()
    return service


def default_plugin_lookup(plugin_id: str) -> PluginDefinition | None:
    return _default_registry().get_plugin(plugin_id, include_disabled=True)


def normalise_plugin_config(
    plugin: PluginDefinition, config: dict[str, Any], *, strict: bool
) -> dict[str, Any]:
    """Copy of ``config`` with every string value of a ``boolean`` field turned into a bool.

    ``strict`` (on save) raises ``ValueError`` naming the key for an unrecognised string; the
    lenient mode (on read) leaves such a value alone so one bad row cannot make the workflow
    unreadable.
    """
    out = dict(config)
    for field in plugin.metadata.configuration_input:
        if field.data_type != "boolean" or not isinstance(out.get(field.name), str):
            continue
        try:
            out[field.name] = parse_bool_flag(out, field.name)
        except ValueError:
            if strict:
                raise
    return out


def normalise_canvas_nodes(
    nodes: list[dict[str, Any]],
    lookup: PluginLookup = default_plugin_lookup,
    *,
    strict: bool,
) -> list[dict[str, Any]]:
    """Nodes with normalised ``pluginConfig`` booleans; other nodes and keys are untouched."""
    result: list[dict[str, Any]] = []
    for node in nodes:
        data = node.get("data") if isinstance(node, dict) else None
        if not isinstance(data, dict) or not isinstance(data.get("pluginConfig"), dict):
            result.append(node)
            continue
        kind = data.get("kind")
        plugin = lookup(kind) if isinstance(kind, str) else None
        if plugin is None:
            result.append(node)
            continue
        try:
            config = normalise_plugin_config(plugin, data["pluginConfig"], strict=strict)
        except ValueError as exc:
            node_id = node.get("id", "?")
            raise ValueError(f"node {node_id} ({kind}): {exc}") from exc
        if config == data["pluginConfig"]:
            result.append(node)
        else:
            result.append({**node, "data": {**data, "pluginConfig": config}})
    return result
