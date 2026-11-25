"""The Mattermost target (source, team, channel) of a notification step."""

from __future__ import annotations

from typing import Any, NamedTuple

from workflow_steps.common.step_flags import require_text


class MattermostTarget(NamedTuple):
    source_id: str
    team_name: str
    channel_name: str


def parse_mattermost_target(config: dict[str, Any], *, step_id: str) -> MattermostTarget:
    """The three required text values of a Mattermost post; a missing one raises ``ValueError``."""
    return MattermostTarget(
        source_id=require_text(config, "mattermost_source_id", step_id=step_id),
        team_name=require_text(config, "team_name", step_id=step_id),
        channel_name=require_text(config, "channel_name", step_id=step_id),
    )
