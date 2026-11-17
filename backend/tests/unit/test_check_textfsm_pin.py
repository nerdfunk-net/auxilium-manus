"""The URL rules of ``scripts/check_textfsm_pin.py`` (doc/analysis/REVIEW.md, 2026-11-17)."""

from __future__ import annotations

import io
import sys
import urllib.request
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import check_textfsm_pin as pin  # noqa: E402


@pytest.mark.parametrize(
    "url",
    [
        "https://pypi.org/pypi/textfsm/json",
        "https://files.pythonhosted.org/packages/x/textfsm-2.1.0-py3-none-any.whl",
    ],
)
def test_pypi_hosts_over_https_are_allowed(url: str) -> None:
    pin.check_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://pypi.org/pypi/textfsm/json",
        "https://evil.example/textfsm.whl",
        "https://pypi.org.evil.example/x",
        "file:///etc/passwd",
        "https:///nohost",
    ],
)
def test_other_urls_are_refused(url: str) -> None:
    with pytest.raises(ValueError, match="refusing"):
        pin.check_url(url)


def test_a_redirect_off_the_allow_list_is_refused() -> None:
    handler = pin._AllowListRedirects()
    request = urllib.request.Request("https://pypi.org/x")

    with pytest.raises(ValueError, match="refusing"):
        handler.redirect_request(request, io.BytesIO(), 302, "Found", {}, "https://evil.example/x")


class _Opener:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def open(self, url: str, timeout: int) -> Any:
        return io.BytesIO(self._body)


def test_a_body_above_the_cap_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pin, "MAX_BYTES", 10)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: _Opener(b"x" * 11))

    with pytest.raises(ValueError, match="above"):
        pin.fetch("https://pypi.org/pypi/textfsm/json")


def test_a_small_body_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: _Opener(b"{}"))

    assert pin.fetch("https://pypi.org/pypi/textfsm/json") == b"{}"
