from __future__ import annotations

from sqlalchemy import distinct, or_, select
from sqlalchemy.orm import Session

from core.models.inventories import Inventory


class InventoryRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, inventory_id: int) -> Inventory | None:
        return self.db.get(Inventory, inventory_id)

    def get_by_name(self, name: str, username: str, active_only: bool = True) -> Inventory | None:
        stmt = select(Inventory).where(
            Inventory.name == name,
            or_(
                Inventory.scope == "global",
                (Inventory.scope == "private") & (Inventory.created_by == username),
            ),
        )
        if active_only:
            stmt = stmt.where(Inventory.is_active.is_(True))
        return self.db.scalar(stmt)

    def list_inventories(
        self,
        username: str,
        active_only: bool = True,
        scope: str | None = None,
        group_path_filter: str | None = None,
    ) -> list[Inventory]:
        if scope == "global":
            stmt = select(Inventory).where(Inventory.scope == "global")
        elif scope == "private":
            stmt = select(Inventory).where(
                Inventory.scope == "private",
                Inventory.created_by == username,
            )
        else:
            stmt = select(Inventory).where(
                or_(
                    Inventory.scope == "global",
                    (Inventory.scope == "private") & (Inventory.created_by == username),
                )
            )

        if active_only:
            stmt = stmt.where(Inventory.is_active.is_(True))

        if group_path_filter is not None:
            stmt = stmt.where(
                or_(
                    Inventory.group_path == group_path_filter,
                    Inventory.group_path.like(f"{group_path_filter}/%"),
                )
            )

        return list(self.db.scalars(stmt.order_by(Inventory.updated_at.desc())).all())

    def get_distinct_group_paths(self, username: str) -> list[str]:
        stmt = (
            select(distinct(Inventory.group_path))
            .where(
                Inventory.is_active.is_(True),
                Inventory.group_path.isnot(None),
                or_(
                    Inventory.scope == "global",
                    (Inventory.scope == "private") & (Inventory.created_by == username),
                ),
            )
        )
        return [row[0] for row in self.db.execute(stmt).all()]

    def rename_group(self, old_path: str, new_path: str, username: str) -> int:
        stmt = select(Inventory).where(
            or_(
                Inventory.group_path == old_path,
                Inventory.group_path.like(old_path + "/%"),
            ),
            Inventory.is_active.is_(True),
            or_(
                Inventory.scope == "global",
                (Inventory.scope == "private") & (Inventory.created_by == username),
            ),
        )
        inventories = list(self.db.scalars(stmt).all())
        for inv in inventories:
            if inv.group_path == old_path:
                inv.group_path = new_path
            elif inv.group_path:
                inv.group_path = new_path + inv.group_path[len(old_path) :]
        self.db.commit()
        return len(inventories)

    def search_inventories(
        self, query_text: str, username: str, active_only: bool = True
    ) -> list[Inventory]:
        pattern = f"%{query_text}%"
        stmt = select(Inventory).where(
            or_(Inventory.name.ilike(pattern), Inventory.description.ilike(pattern)),
            or_(
                Inventory.scope == "global",
                (Inventory.scope == "private") & (Inventory.created_by == username),
            ),
        )
        if active_only:
            stmt = stmt.where(Inventory.is_active.is_(True))
        return list(self.db.scalars(stmt.order_by(Inventory.updated_at.desc())).all())

    def create(self, **kwargs) -> Inventory:
        inventory = Inventory(**kwargs)
        self.db.add(inventory)
        self.db.commit()
        self.db.refresh(inventory)
        return inventory

    def update(self, inventory_id: int, **kwargs) -> Inventory | None:
        inventory = self.get_by_id(inventory_id)
        if inventory is None:
            return None
        for key, value in kwargs.items():
            if hasattr(inventory, key):
                setattr(inventory, key, value)
        self.db.commit()
        self.db.refresh(inventory)
        return inventory

    def get_active_count(self) -> int:
        from sqlalchemy import func

        return self.db.scalar(
            select(func.count()).select_from(Inventory).where(Inventory.is_active.is_(True))
        ) or 0

    def get_total_count(self) -> int:
        from sqlalchemy import func

        return self.db.scalar(select(func.count()).select_from(Inventory)) or 0

    def delete(self, inventory_id: int) -> bool:
        inventory = self.get_by_id(inventory_id)
        if inventory is None:
            return False
        self.db.delete(inventory)
        self.db.commit()
        return True
