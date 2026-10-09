"""Startup check for private inventories whose owner no longer exists (S14)."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from repositories.inventory_repository import InventoryRepository
from repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


def warn_about_orphaned_inventories(db: Session) -> list[str]:
    """Log (and return) the creators of private inventories that no user owns any more.

    Such rows can be inherited by a later holder of the same username, so an operator
    should delete or reassign them. Cleanup is manual after review.
    """
    orphaned = InventoryRepository(db).list_orphaned_private_creators(
        {user.username for user in UserRepository(db).list_users()}
    )
    if orphaned:
        logger.warning(
            "Private inventories exist for users that no longer exist: %s. "
            "Delete or reassign them (see doc/analysis/FABLE_MERGE_20261009.md S14): "
            "DELETE FROM inventories WHERE scope='private' "
            "AND created_by NOT IN (SELECT username FROM users);",
            ", ".join(orphaned),
        )
    return orphaned
