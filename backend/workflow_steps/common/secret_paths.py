"""Secret-path rendering shared by secret-set, secret-get and secret-generate.

The generic template renderer only replaces characters that are unsafe in a file name; the Secret
Manager path rules are stricter (no ``(``, ``#``, ``,`` or non-ASCII). Rendering maps every
rejected character to ``_`` per segment so a device called ``Büro-sw (alt)`` gets a valid path
instead of aborting the step after earlier devices were written. The ``/`` separators come from
the template only.
"""

from __future__ import annotations

import re

from models.failure import FailureInfo
from models.workflow_context import DeviceContext, DeviceError, DeviceStatus
from services.secret_manager.exceptions import (
    SecretManagerAuthError,
    SecretManagerError,
    SecretManagerPermissionError,
    SecretManagerUnavailableError,
)
from services.secret_manager.validation import validate_kv_path
from services.workflow_context.device_template import (
    TemplateRenderOptions,
    render_device_template,
)
from workflow_steps.common.duplicate_keys import (
    DUPLICATE_KEY_CODE,
    DUPLICATE_KEY_FAILURE,
    find_duplicate_keys,
)
from workflow_steps.common.partial_outcomes import mark_device_failed

INVALID_PATH_CODE = "invalid_secret_path"
INVALID_PATH_FAILURE = FailureInfo(phase="internal", kind="bad_request")

_SEGMENT_UNSAFE = re.compile(r"[^A-Za-z0-9 _.@=+-]")


def render_secret_path(template: str, device: DeviceContext, *, strict: bool, run_id: str) -> str:
    """Render, map rejected characters per segment, then validate (still raises ``ValueError``
    for ``..`` and empty segments)."""
    options = TemplateRenderOptions(strict=strict, run_id=run_id)
    segments: list[str] = []
    for template_segment in template.split("/"):
        if not template_segment.strip():
            segments.append("")  # validate_kv_path rejects the empty segment
            continue
        # Render one template segment at a time so a '/' inside a device name cannot add a level.
        rendered = render_device_template(template_segment, device, options=options)
        segments.append(_SEGMENT_UNSAFE.sub("_", rendered.replace("/", "_")))
    path = "/".join(segments)
    return validate_kv_path(path)


def secret_manager_failure(exc: SecretManagerError) -> FailureInfo:
    """Closed-vocabulary classification of a Secret Manager client error."""
    if isinstance(exc, SecretManagerAuthError):
        return FailureInfo(phase="auth", kind="auth_failed", exception_type=type(exc).__name__)
    if isinstance(exc, SecretManagerPermissionError):
        return FailureInfo(phase="api", kind="permission_denied", exception_type=type(exc).__name__)
    if isinstance(exc, SecretManagerUnavailableError):
        return FailureInfo(
            phase="api", kind="server_error", retryable=True, exception_type=type(exc).__name__
        )
    return FailureInfo(phase="api", kind="unknown", exception_type=type(exc).__name__)


def fail_device(
    *, device: DeviceContext, node_id: str, step_id: str, code: str, message: str
) -> DeviceContext:
    """Mark one device failed with a plain error (no structured ``FailureInfo``)."""
    err = DeviceError(node_id=node_id, step_id=step_id, code=code, message=message)
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
    )


def resolve_secret_paths(
    *,
    devices: dict[str, DeviceContext],
    path_template: str,
    strict: bool,
    run_id: str,
    node_id: str,
    step_id: str,
) -> tuple[dict[str, str], dict[str, DeviceContext]]:
    """Render every device's secret path first. A device whose path is invalid, or collides with
    an earlier device's path, fails alone (``a:b`` and ``a_b`` must not share one secret)."""
    paths: dict[str, str] = {}
    failed: dict[str, DeviceContext] = {}
    for device_id, device in devices.items():
        try:
            paths[device_id] = render_secret_path(
                path_template, device, strict=strict, run_id=run_id
            )
        except ValueError as exc:
            failed[device_id] = mark_device_failed(
                device,
                node_id=node_id,
                step_id=step_id,
                code=INVALID_PATH_CODE,
                message=str(exc),
                failure=INVALID_PATH_FAILURE,
            )
    for device_id, owner in find_duplicate_keys(paths.items()).items():
        failed[device_id] = mark_device_failed(
            devices[device_id],
            node_id=node_id,
            step_id=step_id,
            code=DUPLICATE_KEY_CODE,
            message=(
                f"secret path {paths.pop(device_id)!r} is also used by device "
                f"{devices[owner].name!r}; secret paths are keyed by the rendered template"
            ),
            failure=DUPLICATE_KEY_FAILURE,
        )
    return paths, failed
