from __future__ import annotations

import logging
import math
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from models.reports import RESERVED_FIELD_NAMES
from repositories.report_data_records_repository import ReportDataRecordRepository
from repositories.report_datasets_repository import ReportDatasetRepository

logger = logging.getLogger(__name__)

# Guard against a runaway list (e.g. a route table) flooding the table.
MAX_ITEMS_PER_DEVICE = 5000
# Report fields are short facts, not blobs; keep one value from bloating the table.
MAX_STRING_LENGTH = 2000

_DATASET_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")
_FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def validate_dataset_name(name: str) -> str:
    """Return the stripped dataset name, or raise ``ValueError``."""
    cleaned = (name or "").strip()
    if not _DATASET_RE.fullmatch(cleaned):
        raise ValueError(
            "dataset must be 1-100 characters: lowercase letters, digits, '_' or '-', "
            "starting with a letter or digit"
        )
    return cleaned


def validate_field_name(name: str) -> str:
    """Return the field name, or raise ``ValueError``."""
    if name in RESERVED_FIELD_NAMES:
        raise ValueError(
            f"field name {name!r} is reserved by the Reports app "
            f"({', '.join(sorted(RESERVED_FIELD_NAMES))})"
        )
    if not _FIELD_RE.fullmatch(name or ""):
        raise ValueError(
            f"field name {name!r} must be 1-64 characters: lowercase letters, digits or '_', "
            "starting with a letter"
        )
    return name


def _is_scalar(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    return isinstance(value, float) and math.isfinite(value)


class ReportDataService:
    def __init__(self, db: Session) -> None:
        self.repository = ReportDataRecordRepository(db)
        self.datasets = ReportDatasetRepository(db)

    def record_device_data(
        self,
        *,
        device_name: str,
        dataset: str,
        data: dict[str, Any],
        run_id: int | None = None,
        node_id: str | None = None,
    ) -> None:
        """Validate and append one device's flat scalar fields (one row) for *dataset*."""
        dataset = self._validate_target(device_name, dataset)
        self.repository.replace_rows(
            device_name=device_name,
            dataset=dataset,
            rows=[self._validate_row(data)],
            run_id=run_id,
            node_id=node_id,
        )
        self._update_catalog(dataset, "device", list(data))

    def record_device_items(
        self,
        *,
        device_name: str,
        dataset: str,
        items: list[dict[str, Any]],
        run_id: int | None = None,
        node_id: str | None = None,
        field_names: list[str] | None = None,
    ) -> None:
        """Validate and append one device's items (one row each) for *dataset*.

        An empty *items* list is meaningful ("this device has none") and is stored as a
        marker so it supersedes an older collection.
        """
        dataset = self._validate_target(device_name, dataset)
        if len(items) > MAX_ITEMS_PER_DEVICE:
            raise ValueError(
                f"a device may store at most {MAX_ITEMS_PER_DEVICE} items per collection "
                f"(got {len(items)})"
            )
        rows = []
        for index, item in enumerate(items):
            try:
                rows.append(self._validate_row(item))
            except ValueError as exc:
                raise ValueError(f"item {index}: {exc}") from exc
        self.repository.replace_rows(
            device_name=device_name,
            dataset=dataset,
            rows=rows,
            run_id=run_id,
            node_id=node_id,
        )
        if field_names is None:
            field_names = list(rows[0]) if rows else []
        self._update_catalog(dataset, "items", field_names)

    def purge_older_than_days(self, days: int, *, batch_size: int = 1000) -> int:
        """Retention sweep; ``days < 1`` keeps everything. See the repository for what stays."""
        if days < 1:
            return 0
        deleted = self.repository.purge_older_than(
            datetime.now(UTC) - timedelta(days=days), batch_size=batch_size
        )
        logger.info("Purged %s report data row(s) older than %s day(s)", deleted, days)
        return deleted

    def _update_catalog(self, dataset: str, mode: str, field_names: list[str]) -> None:
        """Keep the dataset catalog current. Best effort: the collection is already stored, a
        failed catalog write only delays the entry until the next collection."""
        try:
            self.datasets.upsert(dataset=dataset, mode=mode, field_names=field_names)
        except SQLAlchemyError as exc:
            logger.warning(
                "report dataset catalog update failed dataset=%s error=%s",
                dataset,
                type(exc).__name__,
            )

    @staticmethod
    def _validate_target(device_name: str, dataset: str) -> str:
        if not device_name:
            raise ValueError("device_name is required")
        return validate_dataset_name(dataset)

    @staticmethod
    def _validate_row(data: dict[str, Any]) -> dict[str, Any]:
        if not data:
            raise ValueError("data must contain at least one field")
        for field_name, value in data.items():
            validate_field_name(field_name)
            if not _is_scalar(value):
                raise ValueError(
                    f"field {field_name!r} must be a string, number, boolean or null "
                    f"(got {type(value).__name__})"
                )
            if isinstance(value, str) and len(value) > MAX_STRING_LENGTH:
                raise ValueError(
                    f"field {field_name!r} holds a string of {len(value)} characters; "
                    f"at most {MAX_STRING_LENGTH} are stored"
                )
        return dict(data)
