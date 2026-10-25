import textwrap
from pathlib import Path

import pytest

from manus_agent.registry import HandlerRegistry, builtin_registry, handler


def test_register_and_lookup():
    registry = HandlerRegistry()
    registry.register("greet", lambda params, inputs: {"hi": 1})
    assert registry.get("greet")({}, {}) == {"hi": 1}
    assert registry.get("missing") is None
    assert registry.names() == ["greet"]


@pytest.mark.parametrize("name", ["", "has space", "a/b", "../x", "x" * 65, "1abc"])
def test_invalid_names_are_rejected(name):
    with pytest.raises(ValueError):
        HandlerRegistry().register(name, lambda p, i: {})


def test_duplicate_names_are_rejected():
    registry = HandlerRegistry()
    registry.register("a", lambda p, i: {})
    with pytest.raises(ValueError, match="already registered"):
        registry.register("a", lambda p, i: {})


def test_builtin_echo_returns_its_inputs():
    registry = builtin_registry()
    inputs = {"nonce": "abc", "nested": {"a": [1, 2]}}
    assert registry.get("echo")({}, inputs) == inputs
    assert "echo" in registry.names()


def test_decorator_uses_the_function_name_or_an_explicit_one():
    @handler()
    def by_function_name(params, inputs):
        return {}

    @handler("explicit")
    def other(params, inputs):
        return {}

    assert by_function_name._manus_handler_name == "by_function_name"
    assert other._manus_handler_name == "explicit"


def _write(directory: Path, name: str, body: str) -> None:
    (directory / name).write_text(textwrap.dedent(body))


def test_load_directory_registers_decorated_functions_only(tmp_path):
    _write(
        tmp_path,
        "geo.py",
        """
        from manus_agent.registry import handler

        @handler("resolve")
        def resolve(params, inputs):
            return {"ok": True}

        @handler()
        async def slow(params, inputs):
            return {"async": True}

        def helper():
            return 1
        """,
    )
    private = (
        "from manus_agent.registry import handler\n"
        "@handler('hidden')\n"
        "def h(p, i): return {}\n"
    )
    _write(tmp_path, "_private.py", private)
    (tmp_path / "notes.txt").write_text("ignored")
    registry = HandlerRegistry()
    registry.load_directory(tmp_path)
    assert registry.names() == ["resolve", "slow"]


def test_load_directory_reports_a_broken_module_with_its_file_name(tmp_path):
    _write(tmp_path, "broken.py", "raise RuntimeError('boom')\n")
    with pytest.raises(RuntimeError, match="broken.py"):
        HandlerRegistry().load_directory(tmp_path)


def test_load_directory_rejects_duplicate_names_across_files(tmp_path):
    body = "from manus_agent.registry import handler\n@handler('same')\ndef f(p, i): return {}\n"
    _write(tmp_path, "a.py", body)
    _write(tmp_path, "b.py", body)
    with pytest.raises(ValueError, match="already registered"):
        HandlerRegistry().load_directory(tmp_path)


def test_missing_directory_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        HandlerRegistry().load_directory(tmp_path / "nope")
