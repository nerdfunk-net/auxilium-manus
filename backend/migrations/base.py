from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.orm import DeclarativeBase


class BaseMigration(ABC):
    def __init__(self, engine: Engine, base: type[DeclarativeBase]) -> None:
        self.engine = engine
        self.base = base

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def upgrade(self) -> dict[str, Any]:
        raise NotImplementedError
