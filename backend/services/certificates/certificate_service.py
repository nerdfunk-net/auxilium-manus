"""Filesystem-backed CA certificate manager (dev/admin tools).

Not DB-backed, so no repository layer — same rationale as the Nautobot service
layer wrapping an external resource instead of local persistence.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path

from fastapi import UploadFile

from core.config import CONFIG_CERTS_DIR, SYSTEM_CA_DIR
from models.certificates import AddCertificateResponse, CertificateInfo, ScanResponse

logger = logging.getLogger(__name__)

_SAFE_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+\.crt$")


def _sanitize_crt_filename(filename: str) -> str:
    """Strip any path components and validate as a bare, safe .crt filename."""
    name = Path(filename).name
    if not _SAFE_FILENAME_PATTERN.fullmatch(name):
        raise ValueError(f"Invalid certificate filename: {filename!r}")
    return name


class CertificateService:
    def __init__(
        self,
        config_certs_dir: Path = CONFIG_CERTS_DIR,
        system_ca_dir: Path = SYSTEM_CA_DIR,
    ) -> None:
        self.config_certs_dir = config_certs_dir
        self.system_ca_dir = system_ca_dir

    def scan(self) -> ScanResponse:
        self.config_certs_dir.mkdir(parents=True, exist_ok=True)

        certificates = [
            CertificateInfo(
                filename=cert_file.name,
                path=str(cert_file),
                size=cert_file.stat().st_size,
                exists_in_system=(self.system_ca_dir / cert_file.name).exists(),
            )
            for cert_file in sorted(self.config_certs_dir.glob("*.crt"))
        ]

        return ScanResponse(
            certificates=certificates,
            certs_directory=str(self.config_certs_dir),
        )

    async def upload(self, file: UploadFile) -> CertificateInfo:
        if not file.filename:
            raise ValueError("No filename provided")

        safe_name = _sanitize_crt_filename(file.filename)
        content = await file.read()

        if b"-----BEGIN CERTIFICATE-----" not in content:
            raise ValueError("File does not look like a PEM certificate")

        self.config_certs_dir.mkdir(parents=True, exist_ok=True)
        target = self.config_certs_dir / safe_name
        if target.exists():
            raise FileExistsError(f"Certificate already exists: {safe_name}")

        target.write_bytes(content)

        return CertificateInfo(
            filename=safe_name,
            path=str(target),
            size=target.stat().st_size,
            exists_in_system=(self.system_ca_dir / safe_name).exists(),
        )

    def add_to_system(self, filename: str) -> AddCertificateResponse:
        safe_name = _sanitize_crt_filename(filename)
        source = self.config_certs_dir / safe_name
        if not source.exists():
            raise FileNotFoundError(f"Certificate not found: {safe_name}")

        try:
            self.system_ca_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, self.system_ca_dir / safe_name)
        except PermissionError:
            return AddCertificateResponse(
                success=False,
                message="Permission denied — adding certificates to the system "
                "store requires root/sudo.",
                error="permission_denied",
            )

        try:
            result = subprocess.run(
                ["update-ca-certificates"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except FileNotFoundError:
            return AddCertificateResponse(
                success=False,
                message="update-ca-certificates not found (not running in Docker?).",
                error="binary_not_found",
            )
        except subprocess.TimeoutExpired:
            return AddCertificateResponse(
                success=False,
                message="update-ca-certificates timed out.",
                error="timeout",
            )

        if result.returncode != 0:
            return AddCertificateResponse(
                success=False,
                message=f"update-ca-certificates exited with code {result.returncode}.",
                error="update_failed",
                command_output=result.stderr or result.stdout,
            )

        return AddCertificateResponse(
            success=True,
            message=f"{safe_name} added to the system CA store.",
            command_output=result.stdout,
        )

    def delete(self, filename: str) -> None:
        safe_name = _sanitize_crt_filename(filename)
        target = self.config_certs_dir / safe_name
        if not target.exists():
            raise FileNotFoundError(f"Certificate not found: {safe_name}")
        target.unlink()
