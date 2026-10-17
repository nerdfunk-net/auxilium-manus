"""O1-02: a foreign-key column added to an existing table keeps its constraint and ON DELETE rule.

``CREATE TABLE`` always created the foreign keys; ``ADD COLUMN`` did not, so an upgraded database
silently differed from a fresh install (and ``sync.py`` reported "in sync").
"""

from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy import ForeignKey, Integer, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from migrations.auto_schema import AutoSchemaMigration


class _Base(DeclarativeBase):
    metadata = MetaData()


class _Parent(_Base):
    __tablename__ = "fk_parent"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)


class _Child(_Base):
    __tablename__ = "fk_child"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(20), nullable=True)
    owner_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("fk_parent.id", ondelete="SET NULL"), nullable=True
    )
    parent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("fk_parent.id", ondelete="CASCADE"), nullable=True
    )
    plain_ref_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("fk_parent.id"), nullable=True
    )


def _migration() -> tuple[AutoSchemaMigration, MagicMock]:
    engine = MagicMock()
    conn = engine.connect.return_value.__enter__.return_value
    return AutoSchemaMigration(engine, _Base), conn


def _column(name: str):
    return _Child.__table__.columns[name]


def test_no_statement_for_a_plain_column() -> None:
    migration, _ = _migration()
    assert migration.foreign_key_statements(_column("name")) == []


def test_set_null_rule_is_carried_over() -> None:
    migration, _ = _migration()
    assert migration.foreign_key_statements(_column("owner_id")) == [
        "ALTER TABLE fk_child ADD CONSTRAINT fk_child_owner_id_fkey "
        "FOREIGN KEY (owner_id) REFERENCES fk_parent (id) ON DELETE SET NULL"
    ]


def test_cascade_rule_is_carried_over() -> None:
    migration, _ = _migration()
    (statement,) = migration.foreign_key_statements(_column("parent_id"))
    assert statement.endswith("ON DELETE CASCADE")


def test_a_foreign_key_without_a_rule_has_no_on_delete_clause() -> None:
    migration, _ = _migration()
    (statement,) = migration.foreign_key_statements(_column("plain_ref_id"))
    assert "ON DELETE" not in statement
    assert "REFERENCES fk_parent (id)" in statement


def test_add_columns_adds_the_constraint_in_the_same_transaction() -> None:
    migration, conn = _migration()

    result = migration.add_columns([("fk_child", "owner_id")])

    executed = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert executed[0].startswith("ALTER TABLE fk_child ADD COLUMN owner_id")
    assert executed[1].startswith("ALTER TABLE fk_child ADD CONSTRAINT fk_child_owner_id_fkey")
    conn.commit.assert_called_once()
    assert result.succeeded == ["fk_child.owner_id"]


def test_a_failing_constraint_rolls_the_column_back_and_is_reported() -> None:
    migration, conn = _migration()
    conn.execute.side_effect = [None, RuntimeError("violates foreign key")]

    result = migration.add_columns([("fk_child", "owner_id")])

    conn.commit.assert_not_called()
    assert result.succeeded == []
    assert result.failed and result.failed[0][0] == "fk_child.owner_id"
