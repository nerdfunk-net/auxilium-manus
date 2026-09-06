"""Executor for the decrypt-attribute workflow step.

Two modes:

* **Scalar** (default) — ``source_path`` names one ciphertext token; the
  decrypted cleartext is written to ``destination_path`` sealed.
* **List** (``item_field`` set) — ``source_path`` resolves to a list; the step
  decrypts ``item_field`` on every entry that carries a token and rewrites the
  list (in place, or at ``destination_path``) with each of those fields sealed.
  This handles a Nautobot config-context ``credentials`` array of unknown
  length / unknown usernames.

A sealed value is redacted in every persisted run artifact and revealed
in-memory only to trusted consumers such as the Jinja renderer (see
doc/WORKFLOW-STEPS.md "Secret-valued attributes"). ``jinja_render`` unwraps
sealed leaves inside lists too, so a template can loop the array.

Configuration errors (missing path/credential, unknown algorithm override, no
DB session, ``destination_path`` reserved/misformed) raise and fail the step. A
per-device data failure — wrong shared secret, corrupted token, or the source
not being a list in list mode — routes that device to the ``failure`` outcome
with a ``DeviceError`` so a downstream ``notify-on-error`` /
``notify-mattermost`` step can report it, without stopping the run.
"""

from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

from core.models.runs import WorkflowRun
from core.passphrase_cipher import (
    PassphraseCipherError,
    decrypt_with_passphrase,
    normalize_algorithm,
)
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.workflow_context.attribute_path import (
    resolve_device_attribute,
    resolve_device_value,
)
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.common.attribute_write import set_device_attribute
from workflow_steps.common.credential_resolver import resolve_shared_secret_credential

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "decrypt-attribute"
_RESERVED_BAG_NAMES = frozenset({"parsed", "run_input"})


class _DecryptConfig:
    __slots__ = (
        "source_path",
        "destination_path",
        "credential_reference",
        "algorithm_override",
        "item_field",
    )

    def __init__(self, config: dict[str, Any]) -> None:
        self.source_path = str(config.get("source_path") or "").strip()
        self.destination_path = str(config.get("destination_path") or "").strip()
        self.credential_reference = str(config.get("credential_reference") or "").strip()
        self.algorithm_override = str(config.get("algorithm") or "").strip() or None
        self.item_field = str(config.get("item_field") or "").strip()

        if not self.source_path:
            raise ValueError(f"{_STEP_ID}: source_path is required")
        if not self.credential_reference:
            raise ValueError(f"{_STEP_ID}: credential_reference is required")
        if not self.item_field and not self.destination_path:
            raise ValueError(f"{_STEP_ID}: destination_path is required")
        if self.item_field and "." not in self.write_path:
            raise ValueError(
                f"{_STEP_ID}: in list mode the write target must be bag.field form "
                "(for example nautobot.config_context.credentials)"
            )

    @property
    def is_list_mode(self) -> bool:
        return bool(self.item_field)

    @property
    def write_path(self) -> str:
        # List mode writes back to source_path unless an explicit destination is set.
        return self.destination_path or self.source_path


def _fail_device(
    *, device: DeviceContext, node_id: str, code: str, message: str
) -> DeviceContext:
    err = DeviceError(node_id=node_id, step_id=_STEP_ID, code=code, message=message)
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
    )


def _write_bag_value(device: DeviceContext, path: str, value: Any) -> DeviceContext:
    """Immutably set *value* at ``bag.a.b.leaf`` — copy-on-write, deep-copying
    only the one bag that is touched. Used for list mode, where the value is a
    rebuilt list rather than a scalar leaf."""
    bag_name, remainder = path.split(".", 1)
    if bag_name in _RESERVED_BAG_NAMES:
        raise ValueError(
            f"{_STEP_ID}: {bag_name!r} is a reserved namespace and cannot be written to"
        )

    attribute_bags = dict(device.attribute_bags)
    bag = copy.deepcopy(attribute_bags.get(bag_name, {}))
    cursor = bag
    parts = remainder.split(".")
    for part in parts[:-1]:
        nxt = cursor.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cursor[part] = nxt
        cursor = nxt
    cursor[parts[-1]] = value
    attribute_bags[bag_name] = bag

    return device.model_copy(
        update={
            "attribute_bags": attribute_bags,
            "capabilities": device.capabilities | {Capability.ATTRIBUTES},
        }
    )


def _decrypt_scalar(
    *,
    device: DeviceContext,
    cfg: _DecryptConfig,
    passphrase: str,
    algorithm: str | None,
    node_id: str,
) -> tuple[DeviceContext, str]:
    """Return ``(device, result)`` where result is 'decrypted' | 'skipped' | 'failed'."""
    source_value = resolve_device_attribute(device, cfg.source_path)
    if source_value is None:
        return device, "skipped"
    try:
        cleartext = decrypt_with_passphrase(source_value, passphrase, algorithm=algorithm)
    except PassphraseCipherError as exc:
        logger.warning(
            "%s decryption failed node_id=%s device=%s: %s",
            _STEP_ID,
            node_id,
            device.id,
            exc,
        )
        return (
            _fail_device(
                device=device, node_id=node_id, code="decryption_failed", message=str(exc)
            ),
            "failed",
        )
    updated = set_device_attribute(
        device, cfg.destination_path, seal_secret(cleartext)
    )
    return updated, "decrypted"


def _decrypt_list(
    *,
    device: DeviceContext,
    cfg: _DecryptConfig,
    passphrase: str,
    algorithm: str | None,
    node_id: str,
) -> tuple[DeviceContext, str]:
    """Decrypt ``cfg.item_field`` on every entry of the list at ``source_path``."""
    raw = resolve_device_value(device, cfg.source_path)
    if raw is None:
        return device, "skipped"
    if not isinstance(raw, list):
        return (
            _fail_device(
                device=device,
                node_id=node_id,
                code="not_a_list",
                message=(
                    f"source_path {cfg.source_path!r} did not resolve to a list "
                    "(item_field is set, so list mode is expected)"
                ),
            ),
            "failed",
        )

    new_list: list[Any] = []
    decrypted_here = 0
    for index, element in enumerate(raw):
        if not isinstance(element, dict) or cfg.item_field not in element:
            new_list.append(element)
            continue
        token = element.get(cfg.item_field)
        if not isinstance(token, str) or not token.strip():
            new_list.append(element)
            continue
        try:
            cleartext = decrypt_with_passphrase(token, passphrase, algorithm=algorithm)
        except PassphraseCipherError as exc:
            label = element.get("username") or element.get("name") or f"index {index}"
            message = f"{cfg.item_field} for {label}: {exc}"
            logger.warning(
                "%s decryption failed node_id=%s device=%s: %s",
                _STEP_ID,
                node_id,
                device.id,
                message,
            )
            return (
                _fail_device(
                    device=device,
                    node_id=node_id,
                    code="decryption_failed",
                    message=message,
                ),
                "failed",
            )
        new_list.append({**element, cfg.item_field: seal_secret(cleartext)})
        decrypted_here += 1

    if decrypted_here == 0:
        return device, "skipped"
    return _write_bag_value(device, cfg.write_path, new_list), "decrypted"


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service, device_sessions

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    cfg = _DecryptConfig(config)

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    cred_algorithm, passphrase = resolve_shared_secret_credential(
        db, cfg.credential_reference, acting_user_id=getattr(run, "triggered_by_id", None)
    )
    # A blank override means "trust the token's own algorithm header"; an
    # explicit override is validated here (unknown -> config error) and
    # cross-checked per token at decrypt time.
    algorithm = (
        normalize_algorithm(cfg.algorithm_override) if cfg.algorithm_override else None
    )
    effective_algorithm = algorithm or cred_algorithm

    logger.info(
        "%s started run_id=%s node_id=%s mode=%s algorithm=%s devices=%d",
        _STEP_ID,
        context.run_id,
        node_id,
        "list" if cfg.is_list_mode else "scalar",
        effective_algorithm,
        len(context.devices),
    )

    decrypt_one = _decrypt_list if cfg.is_list_mode else _decrypt_scalar

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}
    decrypted_count = 0
    skipped_count = 0

    for device_id, device in context.devices.items():
        try:
            updated, result = decrypt_one(
                device=device,
                cfg=cfg,
                passphrase=passphrase,
                algorithm=algorithm,
                node_id=node_id,
            )
        except ValueError:
            # Config-level problems (bad destination_path, reserved bag) apply
            # to every device — fail the step, don't route per-device.
            raise
        except Exception as exc:
            raise RuntimeError(
                f"{_STEP_ID}: failed for device {device_id}: {exc}"
            ) from exc

        if result == "failed":
            failed_devices[device_id] = updated
        elif result == "decrypted":
            success_devices[device_id] = updated
            decrypted_count += 1
        else:
            success_devices[device_id] = updated
            skipped_count += 1

    failed_count = len(failed_devices)
    logger.info(
        "%s finished node_id=%s decrypted=%d skipped=%d failed=%d devices=%d",
        _STEP_ID,
        node_id,
        decrypted_count,
        skipped_count,
        failed_count,
        len(context.devices),
    )

    metadata = {
        **context.metadata,
        f"{node_id}.source_path": cfg.source_path,
        f"{node_id}.destination_path": cfg.write_path,
        f"{node_id}.mode": "list" if cfg.is_list_mode else "scalar",
        f"{node_id}.algorithm": effective_algorithm,
        f"{node_id}.decrypted_count": decrypted_count,
        f"{node_id}.skipped_count": skipped_count,
        f"{node_id}.failed_count": failed_count,
    }

    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(
                update={"devices": success_devices, "metadata": metadata}
            ),
        )
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(
                    update={"devices": failed_devices, "metadata": metadata}
                ),
            )
        )
    return outcomes
