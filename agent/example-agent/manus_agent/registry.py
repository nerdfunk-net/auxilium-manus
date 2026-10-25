"""Handlers: the named functions the app can ask this agent to run.

A handler is ``def handle(params: dict, inputs: dict) -> dict`` (or ``async def``). ``params`` is
the static JSON object from the step, ``inputs`` is ``{"attributes": {path: value},
"content": {name: text}}``. It returns a JSON object. Mark it with ``@handler`` and put the file
in the handlers directory; the app only ever sends a handler *name*, never code.
"""

from __future__ import annotations

import importlib.util
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

HANDLER_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_MARK = "_manus_handler_name"

Handler = Callable[[dict[str, Any], dict[str, Any]], Any]


def handler(name: str | None = None) -> Callable[[Handler], Handler]:
    """Mark a function as a handler, named *name* or after the function."""

    def decorate(func: Handler) -> Handler:
        setattr(func, _MARK, name or func.__name__)
        return func

    return decorate


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, name: str, func: Handler) -> None:
        if not HANDLER_NAME_PATTERN.fullmatch(name):
            raise ValueError(
                f"invalid handler name {name!r}: start with a letter, then letters, digits, "
                "'_', '.', '-' (max 64 characters)"
            )
        if name in self._handlers:
            raise ValueError(f"handler {name!r} is already registered")
        self._handlers[name] = func

    def get(self, name: str) -> Handler | None:
        return self._handlers.get(name)

    def names(self) -> list[str]:
        return sorted(self._handlers)

    def load_directory(self, directory: Path) -> None:
        """Import every ``*.py`` file (not starting with ``_``) and register its handlers.

        This executes the files: the handlers directory is code you deployed with the agent.
        """
        if not directory.is_dir():
            raise FileNotFoundError(f"handlers directory not found: {directory}")
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("_"):
                continue
            module = _import_file(path)
            for value in vars(module).values():
                name = getattr(value, _MARK, None)
                if name is not None and callable(value):
                    self.register(name, value)


def _import_file(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(f"manus_agent_handlers.{path.stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load handlers from {path.name}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise RuntimeError(
            f"failed to load handlers from {path.name}: {type(exc).__name__}"
        ) from exc
    return module


def _echo(params: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Health check used by the app's Test connection: returns its inputs unchanged."""
    return inputs


def builtin_registry() -> HandlerRegistry:
    registry = HandlerRegistry()
    registry.register("echo", _echo)
    return registry
