"""Resolve the credentials of a configured source for a workflow step (QW7, W2-05).

Every integration (ISE, ACI, Catalyst Center, Mattermost, ...) has its own source-config service
with ``resolve_credentials(source_id)`` and its own ``*ValidationError``; the "not found" error
derives from ``SourceNotFoundError``, which already formats ``"<display_name> source '<id>' not
found"``. A bad source is a configuration error: ``ValueError`` with the step id in front.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from services.settings.source_config_base import SourceNotFoundError


def resolve_source(
    config_service: Any,
    source_id: str,
    *,
    step_id: str,
    invalid: type[Exception],
    resolve: Callable[[str], Any] | None = None,
) -> Any:
    """``config_service.resolve_credentials(source_id)``, with config problems as ``ValueError``.

    ``invalid`` is the integration's validation error (a source whose settings are incomplete).
    ``resolve`` replaces ``resolve_credentials`` for a service that resolves something else (the
    agent sources resolve a whole connection). Any other exception (a database error, for
    instance) propagates unchanged.
    """
    try:
        return (resolve or config_service.resolve_credentials)(source_id)
    except SourceNotFoundError as exc:
        raise ValueError(f"{step_id}: {exc}") from exc
    except invalid as exc:
        raise ValueError(f"{step_id}: {exc}") from exc
