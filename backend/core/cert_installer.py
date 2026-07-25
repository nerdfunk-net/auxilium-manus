"""
Certificate installation utility for Docker environments.

Installs .crt files from config/certs/ into the system CA store when
INSTALL_CERTIFICATE_FILES=true. No-op outside that flag (e.g. local dev).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from core.config import settings

logger = logging.getLogger(__name__)

SYSTEM_CA_DIR = Path("/usr/local/share/ca-certificates")


def install_certificates(backend_dir: Path) -> None:
    """Copy config/certs/*.crt into the system CA store and refresh it."""
    if not settings.install_certificate_files:
        return

    logger.info("Installing certificates from config/certs/...")

    config_certs_dir = backend_dir / ".." / "config" / "certs"

    if not config_certs_dir.exists():
        logger.info("Certificate directory not found: %s", config_certs_dir)
        return

    cert_files = list(config_certs_dir.glob("*.crt"))
    if not cert_files:
        logger.info("No .crt files found in config/certs/")
        return

    try:
        SYSTEM_CA_DIR.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        logger.error("Permission denied creating %s", SYSTEM_CA_DIR)
        return

    copied_count = 0
    for cert_file in cert_files:
        try:
            shutil.copy2(cert_file, SYSTEM_CA_DIR / cert_file.name)
            logger.info("Copied: %s", cert_file.name)
            copied_count += 1
        except PermissionError:
            logger.error("Permission denied copying %s", cert_file.name)
        except OSError as e:
            logger.error("Failed to copy %s: %s", cert_file.name, e)

    if copied_count == 0:
        logger.info("No certificates were copied")
        return

    logger.info("Running update-ca-certificates...")
    try:
        result = subprocess.run(
            ["update-ca-certificates"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if result.returncode == 0:
            logger.info("Successfully installed %s certificate(s)", copied_count)
        else:
            logger.warning(
                "update-ca-certificates returned %s: %s",
                result.returncode,
                result.stderr,
            )
    except FileNotFoundError:
        logger.warning("update-ca-certificates not found (not running in Docker?)")
    except subprocess.TimeoutExpired:
        logger.warning("update-ca-certificates timed out")
