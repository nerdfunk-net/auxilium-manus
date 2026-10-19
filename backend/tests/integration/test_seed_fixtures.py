"""The session-scoped seed fixtures must not leave ``_seed_session`` in a transaction.

An open transaction on that session holds table locks for the whole run, so the next
``clean_tables`` ``TRUNCATE`` waits on it forever and the suite hangs.
"""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.usefixtures("require_postgres"),
]


def test_admin_user_leaves_no_open_transaction(_seed_session, admin_user) -> None:
    assert admin_user.id is not None
    assert not _seed_session.in_transaction()


def test_ssh_credential_leaves_no_open_transaction(_seed_session, ssh_credential) -> None:
    assert not _seed_session.in_transaction()


def test_git_repository_leaves_no_open_transaction(_seed_session, git_repository) -> None:
    assert not _seed_session.in_transaction()


def test_nautobot_source_leaves_no_open_transaction(_seed_session, nautobot_source) -> None:
    assert not _seed_session.in_transaction()
