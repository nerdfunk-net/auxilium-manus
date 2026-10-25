"""Startup: read config.yaml, update the repository, build the IP index."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path

from manus_agent.data_config import DEFAULT_PATH, DataConfigError, load_data_config
from manus_agent.git_source import GitSourceError, fetch_files
from manus_agent.ip_index import IndexLimitError, IpIndex, build_index

logger = logging.getLogger("manus_agent.data_source")

CONFIG_ENV = "MANUS_AGENT_DATA_CONFIG"


class DataSourceError(RuntimeError):
    """The agent cannot load its data; it must not start with an empty or stale cache."""


def load_index(env: Mapping[str, str]) -> IpIndex:
    path = Path(env.get(CONFIG_ENV, "").strip() or DEFAULT_PATH)
    try:
        config = load_data_config(path, env)
        files = fetch_files(config, env)
    except (DataConfigError, GitSourceError) as exc:
        raise DataSourceError(str(exc)) from exc
    if not files:
        raise DataSourceError(
            f"no file matching '{config.source.filename_pattern}' in "
            f"'{config.source.directory or '.'}'"
        )
    try:
        index = build_index(files, config.source.csv_delimiter, config.mapping)
    except IndexLimitError as exc:
        raise DataSourceError(str(exc)) from exc
    if not index.devices:
        raise DataSourceError("the files contain no device (check the mapping and the delimiter)")
    for warning in index.warnings:
        logger.warning("data: %s", warning)
    logger.info(
        "loaded %d device(s) from %d file(s), %d line(s)",
        len(index.devices),
        index.files_read,
        index.rows,
    )
    return index
