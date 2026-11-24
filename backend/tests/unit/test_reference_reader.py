"""The shared reference reader names the step that asked (it serves two steps)."""

from __future__ import annotations

import pytest

from workflow_steps.common.reference_reader import (
    parse_reference_location,
    read_reference_text,
    validate_reference_config,
)


def test_location_error_names_the_asking_step() -> None:
    with pytest.raises(ValueError, match=r"^compare-pyats-snapshot: reference_location must be"):
        parse_reference_location({"reference_location": "ftp"}, step_id="compare-pyats-snapshot")


def test_default_location_is_the_filesystem() -> None:
    assert parse_reference_location({}, step_id="s") == "filesystem"
    assert parse_reference_location({"reference_location": " GIT "}, step_id="s") == "git"


def test_git_without_a_repository_names_the_step() -> None:
    with pytest.raises(ValueError, match=r"^compare-pyats-snapshot: git_repository_id is required"):
        validate_reference_config({"reference_location": "git"}, step_id="compare-pyats-snapshot")


def test_a_typo_in_pull_before_read_names_the_step() -> None:
    with pytest.raises(ValueError, match="compare-pyats-snapshot"):
        validate_reference_config(
            {"reference_location": "filesystem", "pull_before_read": "ture"},
            step_id="compare-pyats-snapshot",
        )


def test_valid_config_passes() -> None:
    validate_reference_config({"pull_before_read": "yes"}, step_id="s")
    validate_reference_config({}, step_id="s")


@pytest.mark.asyncio
async def test_reading_from_git_without_a_repository_names_the_step() -> None:
    with pytest.raises(ValueError, match=r"^compare-pyats-snapshot: git_repository_id"):
        await read_reference_text(
            config={"reference_location": "git"},
            relative_path="a.cfg",
            step_id="compare-pyats-snapshot",
        )
