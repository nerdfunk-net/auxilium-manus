"""Certificate installation utility for Docker environments.

Installs .crt files from config/certs/ into the system CA store when
INSTALL_CERTIFICATE_FILES=true. No-op outside that flag (e.g. local dev).

Runs on startup in *every* backend process that makes outbound calls — the
FastAPI app (core/start.py) and both Hatchet workers (hatchet/worker.py,
hatchet/dynamic_worker.py) — because docker-compose runs them as separate
containers, each with the certs directory bind-mounted.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from core.config import CONFIG_CERTS_DIR, SYSTEM_CA_DIR, settings

logger = logging.getLogger(__name__)


def install_certificates(
    config_certs_dir: Path = CONFIG_CERTS_DIR,
    system_ca_dir: Path = SYSTEM_CA_DIR,
) -> None:
    """Copy ``config_certs_dir/*.crt`` into the system CA store and refresh it.

    Safe to call unconditionally from any entrypoint: returns immediately unless
    ``INSTALL_CERTIFICATE_FILES`` is set, and never raises — every failure mode
    (missing directory, no certs, permission denied, ``update-ca-certificates``
    absent or failing) is logged and swallowed.
    """
    if not settings.install_certificate_files:
        return

    logger.info("Installing certificates from %s ...", config_certs_dir)

    if not config_certs_dir.exists():
        logger.info("Certificate directory not found: %s", config_certs_dir)
        return

    cert_files = sorted(config_certs_dir.glob("*.crt"))
    if not cert_files:
        logger.info("No .crt files found in %s", config_certs_dir)
        return

    try:
        system_ca_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        logger.error("Permission denied creating %s", system_ca_dir)
        return

    copied_count = 0
    already_installed_count = 0
    for cert_file in cert_files:
        dest = system_ca_dir / cert_file.name
        # A prior root-owned run (e.g. docker/start.sh, before this process
        # dropped to the unprivileged runtime account) may have already
        # installed the identical file. Re-copying it would only fail with a
        # misleading "Permission denied" once running as that unprivileged
        # user — skip it instead of logging a false failure.
        if dest.exists() and dest.read_bytes() == cert_file.read_bytes():
            already_installed_count += 1
            continue
        try:
            shutil.copy2(cert_file, dest)
            logger.info("Copied: %s", cert_file.name)
            copied_count += 1
        except PermissionError:
            logger.error("Permission denied copying %s", cert_file.name)
        except OSError as e:
            logger.error("Failed to copy %s: %s", cert_file.name, e)

    if copied_count == 0:
        if already_installed_count:
            logger.info(
                "%s certificate(s) already installed, nothing to do",
                already_installed_count,
            )
        else:
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
