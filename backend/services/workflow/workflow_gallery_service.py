"""Read-only access to the curated example workflows shipped with the app.

Gallery items are plain ``auxilium-workflow-v1`` export files on disk (see
``contributing-data/workflow-gallery/``) — there is no database table. The
frontend already knows how to validate/parse this shape
(``parseWorkflowExportFile``), so the detail response is returned as-is.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from core.domain_exceptions import NotFoundError
from models.workflows import WorkflowGalleryItem, WorkflowGalleryListResponse

logger = logging.getLogger(__name__)

GALLERY_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

# backend/services/workflow/ -> backend/services -> backend -> repo root
GALLERY_DIR = Path(__file__).resolve().parents[3] / "contributing-data" / "workflow-gallery"


class WorkflowGalleryService:
    """Filesystem-backed catalog of example workflows."""

    def __init__(self, gallery_dir: Path = GALLERY_DIR) -> None:
        self._gallery_dir = gallery_dir

    def list_items(self) -> WorkflowGalleryListResponse:
        items: list[WorkflowGalleryItem] = []
        if not self._gallery_dir.is_dir():
            return WorkflowGalleryListResponse(items=items)

        for path in sorted(self._gallery_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Skipping unreadable gallery workflow %s: %s", path.name, exc)
                continue
            if not isinstance(data, dict):
                logger.warning("Skipping gallery workflow %s: not a JSON object", path.name)
                continue

            name = data.get("name")
            items.append(
                WorkflowGalleryItem(
                    id=path.stem,
                    name=name if isinstance(name, str) and name.strip() else path.stem,
                    description=data.get("description")
                    if isinstance(data.get("description"), str)
                    else None,
                )
            )

        return WorkflowGalleryListResponse(items=items)

    def get_item(self, gallery_id: str) -> dict[str, Any]:
        if not GALLERY_ID_PATTERN.fullmatch(gallery_id):
            raise NotFoundError("Gallery workflow not found.")

        path = (self._gallery_dir / f"{gallery_id}.json").resolve()
        gallery_dir_resolved = self._gallery_dir.resolve()
        if not path.is_relative_to(gallery_dir_resolved) or not path.is_file():
            raise NotFoundError("Gallery workflow not found.")

        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise NotFoundError("Gallery workflow not found.") from exc

        if not isinstance(data, dict):
            raise NotFoundError("Gallery workflow not found.")

        return data
