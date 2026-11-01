from __future__ import annotations

import pytest

from models.git_repositories import GitRepositoryRequest, GitRepositoryUpdateRequest
from services.git.config_path_template import validate_config_path_template

GOOD = [
    "{nautobot.location.name}/{device.name}.running.cfg",
    "{device.name}.cfg",
    "configs/{nautobot.role.name}/{device.name}",
    "  {device.name}.cfg  ",
]
BAD = [
    "fixed.cfg",  # no per-device placeholder
    "{run.date}/x.cfg",  # run only
    "/abs/{device.name}",
    "../{device.name}",
    "a/../{device.name}",
    "a\\{device.name}",
    "C:/{device.name}",
    "{device.name}:x",
    "{bogus.name}/{device.name}",
    "{custom.site}/{device.name}",  # never filled by the assistant reader
    "{git.site}/{device.name}",
    "{name}",
    "{device.na me}",
    "{device.name",
    "x" * 501,
]


@pytest.mark.parametrize("value", GOOD)
def test_good_templates(value: str) -> None:
    assert validate_config_path_template(value) == value.strip()


@pytest.mark.parametrize("value", BAD)
def test_bad_templates(value: str) -> None:
    with pytest.raises(ValueError):
        validate_config_path_template(value)


def test_empty_is_none() -> None:
    assert validate_config_path_template(None) is None
    assert validate_config_path_template("  ") is None


def test_request_validates_and_update_keeps_empty_string() -> None:
    base = {"name": "r", "category": "device_configs", "url": "https://x/y.git"}
    with pytest.raises(ValueError):
        GitRepositoryRequest(**base, config_path_running="fixed.cfg")
    assert GitRepositoryUpdateRequest(config_path_running="").config_path_running == ""
    assert GitRepositoryUpdateRequest().config_path_running is None


def test_service_refuses_templates_on_other_categories() -> None:
    from services.git.repository_service import _check_config_paths

    _check_config_paths("device_configs", {"config_path_running": "{device.name}"})
    _check_config_paths("templates", {"config_path_running": None})
    with pytest.raises(ValueError):
        _check_config_paths("templates", {"config_path_startup": "{device.name}"})


class _Service:
    """Just enough of GitRepositoryService for ``_apply_config_path_rules``."""

    def __init__(self, stored: dict) -> None:
        self.stored = stored

    def get_repository(self, _repo_id: int) -> dict:
        return self.stored


def _apply(stored: dict, patch: dict) -> dict:
    from services.git.repository_service import GitRepositoryService

    patch = dict(patch)
    GitRepositoryService._apply_config_path_rules(_Service(stored), 1, patch)  # type: ignore[arg-type]
    return patch


STORED = {
    "category": "device_configs",
    "config_path_running": "{device.name}.run",
    "config_path_startup": "{device.name}.start",
}


def test_changing_category_alone_clears_both_templates() -> None:
    patch = _apply(STORED, {"category": "templates"})

    assert patch["config_path_running"] is None and patch["config_path_startup"] is None


def test_changing_category_with_a_partial_clear_still_clears_both() -> None:
    patch = _apply(STORED, {"category": "templates", "config_path_running": ""})

    assert patch["config_path_running"] is None and patch["config_path_startup"] is None


def test_changing_category_with_a_template_is_refused() -> None:
    with pytest.raises(ValueError):
        _apply(STORED, {"category": "templates", "config_path_running": "{device.name}"})


def test_device_configs_update_normalises_empty_and_keeps_omitted() -> None:
    patch = _apply(STORED, {"config_path_running": ""})

    assert patch == {"config_path_running": None}


def test_other_category_without_templates_adds_nothing() -> None:
    assert _apply({"category": "templates"}, {"category": "workflows"}) == {"category": "workflows"}
