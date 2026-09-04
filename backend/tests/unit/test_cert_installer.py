"""Unit tests for core.cert_installer.install_certificates.

The installer must never raise: every failure mode (flag off, missing directory,
no certs, permission denied, update-ca-certificates absent / failing / timing out)
is logged and swallowed. subprocess is always stubbed — no real
update-ca-certificates is invoked.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core import cert_installer

_PEM = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"


@pytest.fixture
def system_ca_dir(tmp_path: Path) -> Path:
    return tmp_path / "system-ca"


@pytest.fixture
def certs_dir(tmp_path: Path) -> Path:
    path = tmp_path / "config" / "certs"
    path.mkdir(parents=True)
    return path


@pytest.fixture
def run_mock(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    mock = MagicMock(return_value=MagicMock(returncode=0, stdout="ok", stderr=""))
    monkeypatch.setattr(cert_installer.subprocess, "run", mock)
    return mock


@pytest.fixture
def enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cert_installer.settings, "install_certificate_files", True)


def _write_cert(directory: Path, name: str) -> Path:
    cert = directory / name
    cert.write_text(_PEM)
    return cert


def test_noop_when_flag_disabled(
    monkeypatch: pytest.MonkeyPatch, certs_dir: Path, system_ca_dir: Path, run_mock: MagicMock
) -> None:
    monkeypatch.setattr(cert_installer.settings, "install_certificate_files", False)
    _write_cert(certs_dir, "ca.crt")

    cert_installer.install_certificates(certs_dir, system_ca_dir)

    assert not system_ca_dir.exists()
    run_mock.assert_not_called()


def test_noop_when_source_dir_missing(
    enabled: None, tmp_path: Path, system_ca_dir: Path, run_mock: MagicMock
) -> None:
    cert_installer.install_certificates(tmp_path / "does-not-exist", system_ca_dir)

    assert not system_ca_dir.exists()
    run_mock.assert_not_called()


def test_noop_when_no_crt_files(
    enabled: None, certs_dir: Path, system_ca_dir: Path, run_mock: MagicMock
) -> None:
    (certs_dir / "notes.txt").write_text("not a cert")

    cert_installer.install_certificates(certs_dir, system_ca_dir)

    run_mock.assert_not_called()


def test_installs_single_cert(
    enabled: None, certs_dir: Path, system_ca_dir: Path, run_mock: MagicMock
) -> None:
    _write_cert(certs_dir, "corp-root.crt")

    cert_installer.install_certificates(certs_dir, system_ca_dir)

    assert (system_ca_dir / "corp-root.crt").read_text() == _PEM
    run_mock.assert_called_once()
    assert run_mock.call_args.args[0] == ["update-ca-certificates"]


def test_installs_multiple_certs_with_one_refresh(
    enabled: None, certs_dir: Path, system_ca_dir: Path, run_mock: MagicMock
) -> None:
    _write_cert(certs_dir, "a.crt")
    _write_cert(certs_dir, "b.crt")

    cert_installer.install_certificates(certs_dir, system_ca_dir)

    assert (system_ca_dir / "a.crt").exists()
    assert (system_ca_dir / "b.crt").exists()
    run_mock.assert_called_once()


def test_permission_denied_creating_system_dir_is_swallowed(
    enabled: None,
    certs_dir: Path,
    system_ca_dir: Path,
    run_mock: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _write_cert(certs_dir, "ca.crt")
    monkeypatch.setattr(
        cert_installer.Path, "mkdir", MagicMock(side_effect=PermissionError)
    )

    cert_installer.install_certificates(certs_dir, system_ca_dir)

    run_mock.assert_not_called()
    assert "Permission denied" in caplog.text


def test_permission_denied_copying_cert_skips_refresh(
    enabled: None,
    certs_dir: Path,
    system_ca_dir: Path,
    run_mock: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_cert(certs_dir, "ca.crt")
    monkeypatch.setattr(
        cert_installer.shutil, "copy2", MagicMock(side_effect=PermissionError)
    )

    cert_installer.install_certificates(certs_dir, system_ca_dir)

    run_mock.assert_not_called()


def test_skips_cert_already_installed_by_root(
    enabled: None,
    certs_dir: Path,
    system_ca_dir: Path,
    run_mock: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A prior root-owned run may have already copied the identical file;
    re-copying it as an unprivileged user would only fail with a misleading
    Permission denied. Skip it instead."""
    caplog.set_level("INFO")
    _write_cert(certs_dir, "ca.crt")
    system_ca_dir.mkdir(parents=True)
    _write_cert(system_ca_dir, "ca.crt")

    cert_installer.install_certificates(certs_dir, system_ca_dir)

    run_mock.assert_not_called()
    assert "already installed" in caplog.text


def test_reinstalls_cert_when_content_differs_from_existing(
    enabled: None,
    certs_dir: Path,
    system_ca_dir: Path,
    run_mock: MagicMock,
) -> None:
    _write_cert(certs_dir, "ca.crt")
    system_ca_dir.mkdir(parents=True)
    (system_ca_dir / "ca.crt").write_text("stale content")

    cert_installer.install_certificates(certs_dir, system_ca_dir)

    assert (system_ca_dir / "ca.crt").read_text() == _PEM
    run_mock.assert_called_once()


def test_update_ca_certificates_missing_is_swallowed(
    enabled: None, certs_dir: Path, system_ca_dir: Path, run_mock: MagicMock
) -> None:
    run_mock.side_effect = FileNotFoundError
    _write_cert(certs_dir, "ca.crt")

    cert_installer.install_certificates(certs_dir, system_ca_dir)  # must not raise

    run_mock.assert_called_once()


def test_update_ca_certificates_nonzero_exit_is_swallowed(
    enabled: None,
    certs_dir: Path,
    system_ca_dir: Path,
    run_mock: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    run_mock.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
    _write_cert(certs_dir, "ca.crt")

    cert_installer.install_certificates(certs_dir, system_ca_dir)

    assert "update-ca-certificates returned 1" in caplog.text


def test_update_ca_certificates_timeout_is_swallowed(
    enabled: None, certs_dir: Path, system_ca_dir: Path, run_mock: MagicMock
) -> None:
    run_mock.side_effect = subprocess.TimeoutExpired(cmd="update-ca-certificates", timeout=60)
    _write_cert(certs_dir, "ca.crt")

    cert_installer.install_certificates(certs_dir, system_ca_dir)  # must not raise
