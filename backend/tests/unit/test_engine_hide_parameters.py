"""W9-04: a SQL error never carries the bound parameters (stored device data) in its text."""

from __future__ import annotations

from core.database import engine


def test_engine_hides_bound_parameters_in_errors() -> None:
    assert engine.hide_parameters is True
