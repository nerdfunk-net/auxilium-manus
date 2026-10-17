"""Pure helpers for the split-virtual-chassis step (no I/O).

Turns the one device ``get-virtual-chassis`` produced for a stack (``split_members: false``)
into one device per member, after a command ran once against the whole stack. Each member
keeps the stack's parsed output so a later ``update-attribute`` can pick that member's values
out of it, e.g. ``parsed.parsed.show version.parsed[0].serial[{virtual_chassis.stack_index}]``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from models.workflow_context import DeviceContext, DeviceStatus
from workflow_steps.common.virtual_chassis import bag_name, member_bag

STEP_ID = "split-virtual-chassis"


@dataclass(frozen=True)
class SplitSettings:
    """Validated, immutable view of the step's pluginConfig."""

    attribute_bag: str


def parse_settings(config: dict[str, Any]) -> SplitSettings:
    """Validate ``config``. Raises ``ValueError`` on bad input."""
    return SplitSettings(attribute_bag=bag_name(config, step_id=STEP_ID))


def _member_records(bag: Any) -> list[dict[str, Any]] | None:
    """The bag's ``members`` list, or ``None`` when it is not an unsplit stack bag."""
    if not isinstance(bag, dict):
        return None
    members = bag.get("members")
    if not isinstance(members, list) or not members:
        return None
    records = [m for m in members if isinstance(m, dict) and m.get("id")]
    return records if len(records) == len(members) else None


def split_stack_device(
    device: DeviceContext, settings: SplitSettings
) -> list[DeviceContext] | None:
    """One ``DeviceContext`` per stack member, or ``None`` if ``device`` is not an unsplit stack.

    Members take the Nautobot identity (``source="nautobot"`` and the member's UUID as ``id``,
    which is what ``update-nautobot-device`` trusts) and connect through the stack's address.
    Everything else on the stack device — parsed output, command results, configs — is carried
    over unchanged.
    """
    bag = device.attribute_bags.get(settings.attribute_bag)
    records = _member_records(bag)
    if bag is None or records is None:
        return None

    master = bag.get("master")
    master_name = str(master.get("name") or "") if isinstance(master, dict) else ""
    vc_id = str(bag.get("vc_id") or "")
    vc_name = str(bag.get("vc_name") or device.name)
    other_bags = {k: v for k, v in device.attribute_bags.items() if k != settings.attribute_bag}

    return [
        device.model_copy(
            update={
                "id": str(record["id"]),
                "name": str(record.get("name") or record["id"]),
                "source": "nautobot",
                "attribute_bags": {
                    **other_bags,
                    settings.attribute_bag: member_bag(
                        vc_id=vc_id,
                        vc_name=vc_name,
                        member_count=len(records),
                        record=record,
                        master_name=master_name,
                    ),
                },
                "status": DeviceStatus.OK,
                "errors": [],
            }
        )
        for record in records
    ]
