"""WorkflowGalleryService: listing tolerates malformed files, and item lookup
rejects path traversal / unknown ids instead of reading outside the gallery
directory."""

from __future__ import annotations

import json

import pytest

from core.domain_exceptions import NotFoundError
from services.workflow.workflow_gallery_service import WorkflowGalleryService


@pytest.fixture
def gallery_dir(tmp_path):
    (tmp_path / "get-backups.json").write_text(
        json.dumps({"name": "Get Backups", "description": "Get Backups"})
    )
    (tmp_path / "no-description.json").write_text(json.dumps({"name": "No Description"}))
    (tmp_path / "broken.json").write_text("{not valid json")
    return tmp_path


def test_list_items_skips_malformed_files_and_defaults_missing_fields(gallery_dir) -> None:
    service = WorkflowGalleryService(gallery_dir=gallery_dir)

    result = service.list_items()

    by_id = {item.id: item for item in result.items}
    assert set(by_id) == {"get-backups", "no-description"}
    assert by_id["get-backups"].name == "Get Backups"
    assert by_id["get-backups"].description == "Get Backups"
    assert by_id["no-description"].description is None


def test_list_items_returns_empty_when_directory_missing(tmp_path) -> None:
    service = WorkflowGalleryService(gallery_dir=tmp_path / "does-not-exist")

    result = service.list_items()

    assert result.items == []


def test_get_item_returns_parsed_json(gallery_dir) -> None:
    service = WorkflowGalleryService(gallery_dir=gallery_dir)

    data = service.get_item("get-backups")

    assert data["name"] == "Get Backups"


def test_get_item_rejects_path_traversal(gallery_dir) -> None:
    service = WorkflowGalleryService(gallery_dir=gallery_dir)

    with pytest.raises(NotFoundError):
        service.get_item("../secrets")


def test_get_item_rejects_unknown_id(gallery_dir) -> None:
    service = WorkflowGalleryService(gallery_dir=gallery_dir)

    with pytest.raises(NotFoundError):
        service.get_item("does-not-exist")


def test_get_item_rejects_malformed_json(gallery_dir) -> None:
    service = WorkflowGalleryService(gallery_dir=gallery_dir)

    with pytest.raises(NotFoundError):
        service.get_item("broken")
