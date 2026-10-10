"""T3 guard: tests must not stub ``verify_token`` with a claim-less payload."""

from __future__ import annotations

from pathlib import Path


def test_no_test_stubs_verify_token_with_a_claimless_payload() -> None:
    offenders = [
        f"{path.name}:{lineno}"
        for path in Path(__file__).parent.glob("test_*.py")
        if path.name != Path(__file__).name
        for lineno, line in enumerate(path.read_text().splitlines(), 1)
        if "verify_token]" in line and "token_payload" not in line and "{" in line
    ]
    assert not offenders, "use _auth_helpers.token_payload() (T3): " + ", ".join(offenders)
