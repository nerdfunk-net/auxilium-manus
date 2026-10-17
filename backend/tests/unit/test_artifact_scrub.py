"""S3-05: a session log never stores a secret the run knows about."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from services.artifacts.filesystem_artifact_service import FilesystemArtifactService
from services.workflow_context.secret_fields import (
    REDACTED_PLACEHOLDER,
    register_secret_value,
    run_secret_scope,
)

SECRET = "N3w-TACACS-Key-2026"


def _store(kind: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        service = FilesystemArtifactService(Path(tmp))
        with run_secret_scope():
            register_secret_value(SECRET)
            ref = asyncio.run(
                service.store(
                    content=f"tacacs-server key {SECRET}\n", kind=kind, device_id="d", run_id="r"
                )
            )
        return asyncio.run(service.resolve(ref))


def test_failed_deploy_session_log_is_scrubbed() -> None:
    stored = _store("netmiko_session_log")
    assert SECRET not in stored
    assert REDACTED_PLACEHOLDER in stored


def test_rendered_template_and_config_kinds_are_not_scrubbed() -> None:
    for kind in ("rendered_template", "running_config"):
        assert SECRET in _store(kind)
