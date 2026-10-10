"""First-row creation race: the loser of a unique(user_id) conflict applies onto the winner."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy.exc import IntegrityError

from repositories.user_ai_settings_repository import UserAiSettingsRepository


def test_concurrent_first_save_retries_onto_the_existing_row() -> None:
    winner = SimpleNamespace(enabled=False)
    db = MagicMock()
    repo = UserAiSettingsRepository(db)
    # First lookup: nothing yet. After the conflict the other writer's row is visible.
    lookups = iter([None, winner])
    repo.get_by_user_id = lambda _user_id: next(lookups)  # type: ignore[method-assign]
    db.commit.side_effect = [IntegrityError("insert", {}, Exception("dup")), None]

    result = repo.upsert(1, {"enabled": True})

    assert result is winner
    assert winner.enabled is True
    db.rollback.assert_called_once()
    assert db.commit.call_count == 2
