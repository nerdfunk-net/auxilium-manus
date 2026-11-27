"""Guard 9 (W1-02, W13-07): exception text in a stored message, only from a named class.

D3: Nautobot, Catalyst Center, ACI, ISE, pyATS and the step's own errors (``ValueError``, its
own exception classes) may keep their text; SSH driver, git and database errors persist the
class name and a ``FailureInfo`` (``device_error_from_exception``). A ``message=str(exc)`` or
``message=f"...{exc}..."``, and the message argument of the runner's ``Fail(code, message)``,
therefore need ``exc`` narrowed to a class that is not ``Exception``: by its ``except`` clause or
by an ``isinstance`` check around the site. The sites are pinned per file; the count may only
fall (a new one is a review decision: add it here with its class).
"""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pytest

STEPS_ROOT = Path(__file__).resolve().parents[2] / "workflow_steps"
BROAD = frozenset({"Exception", "BaseException"})

LEGACY_EXCEPTION_TEXT_SITES: dict[str, int] = {
    "workflow_steps/add_ip_to_nautobot/executor.py": 1,
    "workflow_steps/add_pyats_testbed/executor.py": 1,
    "workflow_steps/add_to_ise/executor.py": 2,
    "workflow_steps/batfish_validate_facts/executor.py": 1,
    "workflow_steps/common/pyats_batch.py": 1,
    "workflow_steps/common/secret_paths.py": 1,
    "workflow_steps/compare_data/executor.py": 1,
    # Positional ``Fail(code, message)`` sites, seen since the guard reads them (2026-11-27):
    # FileNotFoundError and (PyATSAPIError, PyATSValidationError).
    "workflow_steps/compare_pyats_snapshot/executor.py": 2,
    # The step's own (PassphraseCipherError, CiscoSecretError).
    "workflow_steps/decrypt_attribute/executor.py": 1,
    "workflow_steps/encrypt_attribute/executor.py": 1,
    "workflow_steps/exists_in_nautobot/executor.py": 1,
    "workflow_steps/get_age_of_backup/executor.py": 1,
    "workflow_steps/get_catalyst_center_client_data/executor.py": 1,
    # The Catalyst Center client's validation / API / auth errors (sanitised by the client).
    "workflow_steps/get_catalyst_center_configs/executor.py": 1,
    "workflow_steps/get_next_free_ip/executor.py": 1,
    "workflow_steps/open_change_request/executor.py": 3,
    "workflow_steps/parse_cisco_config/executor.py": 1,
    "workflow_steps/render_jinja_template/executor.py": 1,
    "workflow_steps/store_for_report/executor.py": 1,
    "workflow_steps/update_attribute/executor.py": 1,
    "workflow_steps/update_ise_tacacs_key/executor.py": 1,
    "workflow_steps/update_nautobot_ip/lookups.py": 1,
}


@dataclass(frozen=True)
class Site:
    line: int
    name: str
    narrowed_to: str | None  # the class text of the except clause or isinstance check


def _text_names(value: ast.expr) -> set[str]:
    """Names whose text the message carries: ``str(x)`` or ``{x}`` in an f-string."""
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "str":
        return {a.id for a in value.args[:1] if isinstance(a, ast.Name)}
    if isinstance(value, ast.JoinedStr):
        return {
            v.value.id
            for v in value.values
            if isinstance(v, ast.FormattedValue) and isinstance(v.value, ast.Name)
        }
    return set()


def _isinstance_of(test: ast.expr, name: str) -> str | None:
    if (
        isinstance(test, ast.Call)
        and isinstance(test.func, ast.Name)
        and test.func.id == "isinstance"
        and len(test.args) == 2
        and isinstance(test.args[0], ast.Name)
        and test.args[0].id == name
    ):
        return ast.unparse(test.args[1])
    return None


def _narrowing(chain: list[ast.AST], name: str) -> tuple[bool, str | None]:
    """(is an exception variable, the class it is narrowed to) walking outwards."""
    for node in chain:
        if isinstance(node, ast.If) and (cls := _isinstance_of(node.test, name)):
            return True, cls
        if isinstance(node, ast.ExceptHandler) and node.name == name:
            return True, ast.unparse(node.type) if node.type else None
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            return _is_exception_parameter(node, name), None
    return False, None


def _is_exception_parameter(function: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> bool:
    """A helper that formats a parameter it never narrowed (``def f(exc): ...str(exc)``)."""
    arguments = (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
    for argument in arguments:
        if argument.arg != name:
            continue
        if argument.annotation is not None:
            return any(word in ast.unparse(argument.annotation) for word in ("Exception", "Error"))
        return name in {"exc", "error", "err", "e"}
    return False


def _messages(tree: ast.AST) -> list[ast.expr]:
    """Every stored message: a ``message=`` keyword, and the second positional argument of the
    runner's ``Fail(code, message, failure)``."""
    found: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "message":
            found.append(node.value)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Fail"
            and len(node.args) >= 2
        ):
            found.append(node.args[1])
    return found


def sites_in(source: str) -> list[Site]:
    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {
        child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)
    }
    found: list[Site] = []
    for message in _messages(tree):
        chain: list[ast.AST] = []
        cursor: ast.AST = message
        while cursor in parents:
            cursor = parents[cursor]
            chain.append(cursor)
        for name in sorted(_text_names(message)):
            is_exception, narrowed = _narrowing(chain, name)
            if is_exception:
                found.append(Site(message.lineno, name, narrowed))
    return found


def _is_safe(site: Site) -> bool:
    if site.narrowed_to is None:
        return False
    classes = {part.strip(" ()") for part in site.narrowed_to.split(",")} - {""}
    return not classes & BROAD


def _all_sites() -> dict[str, list[Site]]:
    return {
        path.relative_to(STEPS_ROOT.parent).as_posix(): found
        for path in sorted(STEPS_ROOT.rglob("*.py"))
        if (found := sites_in(path.read_text()))
    }


def test_exception_text_only_from_a_named_class() -> None:
    unsafe = {
        f: [(s.line, s.name, s.narrowed_to) for s in sites if not _is_safe(s)]
        for f, sites in _all_sites().items()
    }
    unsafe = {f: s for f, s in unsafe.items() if s}
    assert unsafe == {}, (
        "exception text stored from an unnarrowed exception; use device_error_from_exception "
        f"(class name + FailureInfo) or narrow it to the class whose text is safe: {unsafe}"
    )


def test_no_new_exception_text_site() -> None:
    counts = Counter({f: len(s) for f, s in _all_sites().items()})
    grown = {
        f: (LEGACY_EXCEPTION_TEXT_SITES.get(f, 0), n)
        for f, n in counts.items()
        if n > LEGACY_EXCEPTION_TEXT_SITES.get(f, 0)
    }
    assert not grown, f"new exception-text message site (allowed, found): {grown}"


def test_ratchet_list_is_not_stale() -> None:
    counts = {f: len(s) for f, s in _all_sites().items()}
    stale = {
        f: (n, counts.get(f, 0))
        for f, n in LEGACY_EXCEPTION_TEXT_SITES.items()
        if counts.get(f, 0) < n
    }
    assert not stale, f"lower these entries (listed, found); delete at zero: {stale}"


def _one(source: str) -> Site:
    (site,) = sites_in(source)
    return site


@pytest.mark.parametrize(
    "source",
    [
        "try:\n    x()\nexcept ValueError as exc:\n    f(message=str(exc))",
        "try:\n    x()\nexcept (KeyError, ValueError) as exc:\n    f(message=f'bad: {exc}')",
        "try:\n    x()\nexcept Exception as exc:\n    if isinstance(exc, OwnError):\n"
        "        f(message=str(exc))",
        "try:\n    x()\nexcept ValueError as exc:\n    return Fail('bad', str(exc))",
    ],
)
def test_a_narrowed_site_is_safe(source: str) -> None:
    assert _is_safe(_one(source))


@pytest.mark.parametrize(
    "source",
    [
        "try:\n    x()\nexcept Exception as exc:\n    f(message=str(exc))",
        "try:\n    x()\nexcept BaseException as exc:\n    f(message=f'{exc}')",
        "try:\n    x()\nexcept (ValueError, Exception) as exc:\n    f(message=str(exc))",
        "def g(exc: Exception):\n    return f(message=str(exc))",
        "def g(error):\n    return f(message=f'failed: {error}')",
        # The runner's ``Fail(code, message, failure)`` takes the message positionally too.
        "try:\n    x()\nexcept Exception as exc:\n    return Fail('boom', str(exc))",
        "try:\n    x()\nexcept Exception as exc:\n    return Fail('boom', f'failed: {exc}', None)",
    ],
)
def test_an_unnarrowed_site_is_unsafe(source: str) -> None:
    assert not _is_safe(_one(source))


@pytest.mark.parametrize(
    "source",
    [
        "f(message=str(count))",
        "def g(text: str):\n    return f(message=str(text))",
        "f(summary=str(exc))",
        "try:\n    x()\nexcept Exception as exc:\n    return Fail(str(exc))",
        "try:\n    x()\nexcept Exception as exc:\n    return Other('c', str(exc))",
        "try:\n    x()\nexcept ValueError as exc:\n    f(message=type(exc).__name__)",
    ],
)
def test_text_that_is_not_an_exception_is_not_a_site(source: str) -> None:
    assert sites_in(source) == []
