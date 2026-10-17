"""O1-04: finding what still uses a credential before it is deleted.

References are by name or id with no foreign key, so a delete used to leave dangling
references that failed at the next run. The finder reports kind, id and name only.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.models.credentials import Credential
from core.models.git import GitRepository
from core.models.secret_manager import SecretManagerConnection
from core.models.settings import Setting
from core.models.templates import Template
from core.models.users import User
from core.models.workflows import Workflow
from repositories.credential_usage_repository import CredentialUsageRepository
from services.credentials.usage import CredentialDependant, find_dependants


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    tables = [
        User.__table__,
        Credential.__table__,
        GitRepository.__table__,
        SecretManagerConnection.__table__,
        Template.__table__,
        Workflow.__table__,
    ]
    tables.append(Setting.__table__)
    Credential.metadata.create_all(engine, tables=tables)
    session = sessionmaker(bind=engine)()
    session.add(User(id=1, username="owner", email="o@x.y", password_hash="x"))
    session.add(User(id=2, username="other", email="p@x.y", password_hash="x"))
    session.commit()
    yield session
    session.close()
    engine.dispose()


def _credential(
    db: Session, *, name: str = "lab", visibility: str = "global", owner: int | None = None
):
    credential = Credential(
        name=name, username="u", type="ssh", visibility=visibility, owner_user_id=owner
    )
    db.add(credential)
    db.commit()
    return credential


def _node(kind: str, reference: str) -> dict:
    return {
        "id": f"{kind}-1",
        "type": "workflowNode",
        "data": {"kind": kind, "pluginConfig": {"credential_reference": reference}},
    }


def test_unused_credential_has_no_dependants(db: Session) -> None:
    credential = _credential(db)
    assert find_dependants(CredentialUsageRepository(db), credential) == []


def test_git_repository_by_credential_name(db: Session) -> None:
    credential = _credential(db)
    db.add(GitRepository(name="configs", category="device_configs", url="u", credential_name="lab"))
    db.add(GitRepository(name="other", category="device_configs", url="u", credential_name="x"))
    db.commit()

    found = find_dependants(CredentialUsageRepository(db), credential)

    assert found == [CredentialDependant(kind="git_repository", id=1, name="configs")]


def test_secret_manager_connection_by_credential_name(db: Session) -> None:
    credential = _credential(db)
    db.add(SecretManagerConnection(name="bao", backend="openbao", credential_name="lab"))
    db.commit()

    found = find_dependants(CredentialUsageRepository(db), credential)

    assert found == [CredentialDependant(kind="secret_manager", id=1, name="bao")]


def test_template_by_credential_id(db: Session) -> None:
    credential = _credential(db)
    db.add(Template(name="t1", credential_id=credential.id))
    db.add(Template(name="t2", credential_id=credential.id + 99))
    db.commit()

    found = find_dependants(CredentialUsageRepository(db), credential)

    assert found == [CredentialDependant(kind="template", id=1, name="t1")]


def test_source_setting_by_credential_id(db: Session) -> None:
    credential = _credential(db)
    db.add(Setting(key="sources.ise.lab", value={"credential_id": credential.id}))
    db.add(Setting(key="sources.ise.other", value={"credential_id": credential.id + 1}))
    db.add(Setting(key="unrelated", value={"credential_id": "not-an-int"}))
    db.commit()

    found = find_dependants(CredentialUsageRepository(db), credential)

    assert [(d.kind, d.name) for d in found] == [("source", "sources.ise.lab")]


def test_mail_settings_by_credential_name(db: Session) -> None:
    credential = _credential(db)
    db.add(Setting(key="mail.smtp", value={"credential_name": "lab"}))
    db.commit()

    found = find_dependants(CredentialUsageRepository(db), credential)

    assert [(d.kind, d.name) for d in found] == [("mail_settings", "mail.smtp")]


def test_workflow_canvas_reference_by_name(db: Session) -> None:
    credential = _credential(db)
    db.add(Workflow(name="uses", creator_id=1, canvas_nodes=[_node("run-command", "lab")]))
    db.add(Workflow(name="other", creator_id=1, canvas_nodes=[_node("run-command", "else")]))
    db.add(Workflow(name="empty", creator_id=1, canvas_nodes=None))
    db.commit()

    found = find_dependants(CredentialUsageRepository(db), credential)

    assert [(d.kind, d.name) for d in found] == [("workflow", "uses")]


def test_private_credential_ignores_global_only_references(db: Session) -> None:
    """Git, secret manager and mail resolve global credentials only (background jobs)."""
    credential = _credential(db, visibility="private", owner=1)
    db.add(GitRepository(name="configs", category="c", url="u", credential_name="lab"))
    db.add(Setting(key="mail.smtp", value={"credential_name": "lab"}))
    db.add(Workflow(name="mine", creator_id=1, canvas_nodes=[_node("run-command", "lab")]))
    db.add(Workflow(name="theirs", creator_id=2, canvas_nodes=[_node("run-command", "lab")]))
    db.commit()

    found = find_dependants(CredentialUsageRepository(db), credential)

    assert [(d.kind, d.name) for d in found] == [("workflow", "mine")]


def test_dependant_carries_no_secret_fields() -> None:
    assert set(CredentialDependant.__dataclass_fields__) == {"kind", "id", "name"}
