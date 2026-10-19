"""The 4xx leak guard: what it flags and what it leaves alone."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from check_http_4xx_leaks import scan_source  # noqa: E402


def _handler(exc_types: str, detail: str) -> str:
    return (
        "from fastapi import HTTPException\n"
        "def f():\n"
        "    try:\n"
        "        x()\n"
        f"    except {exc_types} as exc:\n"
        f"        raise HTTPException(status_code=400, detail={detail}) from exc\n"
    )


def test_flags_str_of_a_builtin_exception() -> None:
    assert scan_source(_handler("ValueError", "str(exc)"))


def test_flags_an_fstring_and_a_bare_name() -> None:
    assert scan_source(_handler("OSError", 'f"failed: {exc}"'))
    assert scan_source(_handler("Exception", "exc"))


def test_flags_one_builtin_inside_a_tuple_and_dotted_names() -> None:
    assert scan_source(_handler("(DomainThing, ValueError)", "str(exc)"))
    assert scan_source(_handler("FileNotFoundError", "str(exc)"))


def _raw(call: str) -> str:
    return f"def f():\n    try:\n        x()\n    except ValueError as exc:\n        raise {call}\n"


def test_flags_a_positional_detail() -> None:
    assert scan_source(_raw("HTTPException(400, str(exc))"))
    assert scan_source(_raw("HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))"))


def test_flags_the_exception_inside_a_dict_or_list_detail() -> None:
    assert scan_source(_raw('HTTPException(status_code=400, detail={"message": str(exc)})'))
    assert scan_source(_raw('HTTPException(400, {"code": "x", "message": f"bad: {exc}"})'))
    assert scan_source(_raw("HTTPException(status_code=400, detail=[str(exc)])"))


def test_allows_a_positional_or_dict_detail_that_is_sanitized() -> None:
    assert not scan_source(_raw("HTTPException(400, client_error_message(exc))"))
    assert not scan_source(
        _raw('HTTPException(status_code=400, detail={"message": client_error_message(exc)})')
    )
    assert not scan_source(_raw('HTTPException(400, "Invalid request")'))


def test_allows_the_sanitizing_helper() -> None:
    assert not scan_source(_handler("ValueError", "client_error_message(exc)"))


def test_allows_the_projects_own_exception_types() -> None:
    assert not scan_source(_handler("TemplateNotFoundError", "str(exc)"))
    assert not scan_source(_handler("(CredentialNotFoundError, AccessDeniedError)", "str(exc)"))


def test_allows_a_fixed_message() -> None:
    assert not scan_source(_handler("ValueError", '"Invalid request"'))


def test_the_routers_are_clean() -> None:
    routers = Path(__file__).resolve().parents[2] / "routers"
    findings = [
        f"{p.relative_to(routers)}:{line}"
        for p in routers.rglob("*.py")
        for line, _ in scan_source(p.read_text(encoding="utf-8"))
    ]
    assert findings == []
