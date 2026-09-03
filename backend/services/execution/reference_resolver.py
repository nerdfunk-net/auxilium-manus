"""Validate ``type == "reference"`` run-input values against the rows they
point at, scoped to the triggering user.

`resolve_run_inputs` (run_input_validation.py) only checks the *shape* of a
reference value — it is pure and has no DB session. This module does the
existence / access / type checks that need a `Session` and the acting user:
it is called at schedule-save time (`ScheduleService`) so a broken reference
surfaces as a 422 immediately, and again from `scheduled_trigger.dispatch`
so a reference that rotted between save and fire fails the run cleanly.

Adding a new reference kind = one class + one `REF_RESOLVERS` entry here,
plus the matching ``ref_kind`` literal in `models/workflows.py`.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class ReferenceValidationError(ValueError):
    """A ``type == "reference"`` run-input value does not resolve for the acting
    user — unknown row, no access, wrong type, or expired."""


class ReferenceResolver(Protocol):
    kind: str
    label: str

    def validate(self, reference: Any, *, db: Session, acting_user_id: int | None) -> None: ...


def _acting_username(db: Session, acting_user_id: int | None) -> str | None:
    if acting_user_id is None:
        return None
    from repositories.user_repository import UserRepository

    user = UserRepository(db).get_by_id(acting_user_id)
    return user.username if user else None


def _prefer_private(matches: list[dict[str, Any]]) -> dict[str, Any]:
    """Private credential wins over a global one of the same name — mirrors
    ``workflow_steps/common/credential_resolver.py::_resolve_credential``."""
    return next((c for c in matches if c.get("visibility") == "private"), matches[0])


class _InventoryReferenceResolver:
    kind = "inventory"
    label = "inventory"

    def validate(self, reference: Any, *, db: Session, acting_user_id: int | None) -> None:
        from repositories.inventory_repository import InventoryRepository
        from services.sources.nautobot.persistence_service import InventoryService

        try:
            inventory_id = int(reference)
        except (TypeError, ValueError) as exc:
            raise ReferenceValidationError(f"{reference!r} is not a valid inventory id") from exc

        username = _acting_username(db, acting_user_id)
        service = InventoryService(InventoryRepository(db))
        try:
            inventory = service.get_inventory(inventory_id, username=username)
        except PermissionError as exc:
            raise ReferenceValidationError(
                f"inventory {inventory_id} is private to another user"
            ) from exc
        if inventory is None:
            raise ReferenceValidationError(f"inventory {inventory_id} does not exist")
        if not inventory.get("is_active", True):
            raise ReferenceValidationError(f"inventory {inventory_id} is inactive")


class _CredentialReferenceResolver:
    kind = "credential"
    label = "SSH credential"

    def validate(self, reference: Any, *, db: Session, acting_user_id: int | None) -> None:
        from services.credentials.credentials_service import CredentialsService

        name = str(reference or "").strip()
        if not name:
            raise ReferenceValidationError("credential name is empty")

        credentials = CredentialsService(db).list_credentials(
            include_expired=True, source="general", acting_user_id=acting_user_id
        )
        matches = [item for item in credentials if item["name"] == name]
        if not matches:
            raise ReferenceValidationError(f"no credential named {name!r} is visible to you")

        match = _prefer_private(matches)
        if match["type"] != "ssh":
            raise ReferenceValidationError(
                f"credential {name!r} is type {match['type']!r}, expected 'ssh'"
            )
        if match["status"] == "expired":
            raise ReferenceValidationError(f"credential {name!r} is expired")


REF_RESOLVERS: dict[str, ReferenceResolver] = {
    resolver.kind: resolver
    for resolver in (_InventoryReferenceResolver(), _CredentialReferenceResolver())
}


def validate_reference_inputs(
    static_attributes: list[dict[str, Any]] | None,
    run_inputs: dict[str, Any],
    *,
    db: Session,
    acting_user_id: int | None,
) -> None:
    """Validate every ``type == "reference"`` value present in ``run_inputs``
    against the workflow's declared ``static_attributes``, scoped to
    ``acting_user_id``.

    ``run_inputs`` must already have passed
    ``run_input_validation.resolve_run_inputs`` (shape). Raises
    ``ReferenceValidationError`` naming the first offending attribute.
    """
    from models.workflows import StaticAttributeDef

    defs = [StaticAttributeDef.model_validate(raw) for raw in static_attributes or []]
    for attr in defs:
        if attr.type != "reference" or attr.name not in run_inputs:
            continue
        resolver = REF_RESOLVERS.get(attr.ref_kind or "")
        if resolver is None:
            raise ReferenceValidationError(f"{attr.name}: unknown ref_kind {attr.ref_kind!r}")
        try:
            resolver.validate(run_inputs[attr.name], db=db, acting_user_id=acting_user_id)
        except ReferenceValidationError as exc:
            raise ReferenceValidationError(f"{attr.name}: {exc}") from exc
