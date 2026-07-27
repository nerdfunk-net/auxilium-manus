from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from core.models.credentials import Credential
from core.models.users import User


class CredentialsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, cred_id: int) -> Credential | None:
        return self.db.scalar(select(Credential).where(Credential.id == cred_id))

    def get_by_id_for_user(
        self, cred_id: int, *, acting_user_id: int | None
    ) -> Credential | None:
        """Returns None both when the row doesn't exist and when it's a
        private row owned by someone else — callers must not distinguish
        the two cases, to avoid leaking existence of another user's
        private credential."""
        credential = self.get_by_id(cred_id)
        if credential is None:
            return None
        if credential.visibility == "private" and credential.owner_user_id != acting_user_id:
            return None
        return credential

    def get_by_id_with_owner(self, cred_id: int) -> tuple[Credential, str | None] | None:
        row = self.db.execute(
            select(Credential, User.username)
            .outerjoin(User, Credential.owner_user_id == User.id)
            .where(Credential.id == cred_id)
        ).first()
        if row is None:
            return None
        return row[0], row[1]

    def list_visible(
        self, *, acting_user_id: int | None, source: str | None
    ) -> list[tuple[Credential, str | None]]:
        """Global credentials plus the acting user's own private credentials,
        each paired with the owner's username (None for global rows)."""
        stmt = (
            select(Credential, User.username)
            .outerjoin(User, Credential.owner_user_id == User.id)
            .where(
                or_(
                    Credential.visibility == "global",
                    and_(
                        Credential.visibility == "private",
                        Credential.owner_user_id == acting_user_id,
                    ),
                )
            )
        )
        if source:
            stmt = stmt.where(Credential.source == source)
        rows = self.db.execute(stmt.order_by(Credential.name.asc())).all()
        return [(row[0], row[1]) for row in rows]

    def find_global_conflict(
        self, name: str, source: str, *, exclude_id: int | None = None
    ) -> Credential | None:
        stmt = select(Credential).where(
            Credential.visibility == "global",
            Credential.name == name,
            Credential.source == source,
        )
        if exclude_id is not None:
            stmt = stmt.where(Credential.id != exclude_id)
        return self.db.scalar(stmt)

    def find_private_conflict(
        self,
        name: str,
        source: str,
        owner_user_id: int,
        *,
        exclude_id: int | None = None,
    ) -> Credential | None:
        stmt = select(Credential).where(
            Credential.visibility == "private",
            Credential.owner_user_id == owner_user_id,
            Credential.name == name,
            Credential.source == source,
        )
        if exclude_id is not None:
            stmt = stmt.where(Credential.id != exclude_id)
        return self.db.scalar(stmt)

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
