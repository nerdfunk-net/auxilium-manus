from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models.credentials import Credential


class CredentialsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, cred_id: int) -> Credential | None:
        return self.db.scalar(select(Credential).where(Credential.id == cred_id))

    def get_by_name_and_source(self, name: str, source: str) -> Credential | None:
        return self.db.scalar(
            select(Credential).where(
                Credential.name == name,
                Credential.source == source,
            )
        )

    def list_by_source(self, source: str) -> list[Credential]:
        stmt = (
            select(Credential)
            .where(Credential.source == source)
            .order_by(Credential.name.asc())
        )
        return list(self.db.scalars(stmt))

    def list_all(self) -> list[Credential]:
        stmt = select(Credential).order_by(Credential.name.asc())
        return list(self.db.scalars(stmt))

    def list_by_type(self, cred_type: str) -> list[Credential]:
        stmt = select(Credential).where(Credential.type == cred_type)
        return list(self.db.scalars(stmt))

    def create(self, **kwargs) -> Credential:
        credential = Credential(**kwargs)
        self.db.add(credential)
        self.db.commit()
        self.db.refresh(credential)
        return credential

    def update(self, credential: Credential, **kwargs) -> Credential:
        for key, value in kwargs.items():
            setattr(credential, key, value)
        self.db.commit()
        self.db.refresh(credential)
        return credential

    def delete(self, credential: Credential) -> None:
        self.db.delete(credential)
        self.db.commit()
