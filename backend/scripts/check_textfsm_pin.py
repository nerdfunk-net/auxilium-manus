"""Tell when the ``textfsm`` pin in requirements.txt can be raised.

textfsm 2.1.1 ships a top-level ``tests/`` package in its wheel; it shadows ``backend/tests``
(``ModuleNotFoundError: tests.unit``), so ``requirements.txt`` pins ``textfsm==2.1.0``.
This check looks at every release newer than the pin:

* exit 0: no newer release, or every newer release still has the top-level ``tests/``
* exit 1: a newer release has a clean wheel, so the pin can be raised (then run the full pytest)

Standard library only, run weekly by ``.github/workflows/audit.yml``. Network access to pypi.org.
"""

from __future__ import annotations

import io
import json
import re
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse

PYPI_JSON_URL = "https://pypi.org/pypi/textfsm/json"
REQUIREMENTS = Path(__file__).resolve().parent.parent / "requirements.txt"
PIN_PATTERN = re.compile(r"^textfsm==(\d+(?:\.\d+)*)\s*(?:#.*)?$", re.MULTILINE)
RELEASE_PATTERN = re.compile(r"^\d+(?:\.\d+)*$")  # final releases only
TIMEOUT_SECONDS = 60
# The JSON names the wheel URL: check the host (also after a redirect) and cap the body.
ALLOWED_HOSTS = frozenset({"pypi.org", "files.pythonhosted.org"})
MAX_BYTES = 20 * 1024 * 1024


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def pinned_version(requirements_text: str) -> str:
    match = PIN_PATTERN.search(requirements_text)
    if match is None:
        raise SystemExit("requirements.txt has no 'textfsm==<version>' pin; nothing to check")
    return match.group(1)


def newer_releases(releases: dict[str, list[dict]], pin: str) -> list[str]:
    candidates = [
        v
        for v, files in releases.items()
        if RELEASE_PATTERN.match(v) and files and version_key(v) > version_key(pin)
    ]
    return sorted(candidates, key=version_key)


def wheel_url(files: list[dict]) -> str | None:
    for item in files:
        if item.get("packagetype") == "bdist_wheel" and not item.get("yanked"):
            return str(item["url"])
    return None


def has_top_level_tests(wheel_bytes: bytes) -> bool:
    with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as wheel:
        return any(name.split("/", 1)[0] == "tests" for name in wheel.namelist())


def check_url(url: str) -> None:
    """Refuse anything but ``https`` on an allow-listed host."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError(f"refusing URL outside {sorted(ALLOWED_HOSTS)} over https: {url}")


class _AllowListRedirects(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to an allow-listed https URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str) -> bytes:
    check_url(url)
    opener = urllib.request.build_opener(_AllowListRedirects)
    with opener.open(url, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError(f"refusing a response above {MAX_BYTES} bytes: {url}")
    return body


def main() -> int:
    pin = pinned_version(REQUIREMENTS.read_text(encoding="utf-8"))
    releases = json.loads(fetch(PYPI_JSON_URL))["releases"]
    newer = newer_releases(releases, pin)
    if not newer:
        print(f"textfsm {pin} is the newest release; keep the pin.")
        return 0

    clean: list[str] = []
    for version in newer:
        url = wheel_url(releases[version])
        if url is None:
            print(f"textfsm {version}: no wheel on PyPI, skipped")
        elif has_top_level_tests(fetch(url)):
            print(f"textfsm {version}: wheel still has a top-level tests/ package")
        else:
            print(f"textfsm {version}: wheel is clean")
            clean.append(version)

    if clean:
        print(
            f"textfsm {clean[-1]} no longer ships a top-level tests/ package: raise the pin "
            "in backend/requirements.txt, run the full pytest and update doc/OPEN_TODOS.md."
        )
        return 1
    print(f"Pin textfsm=={pin} is still needed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
