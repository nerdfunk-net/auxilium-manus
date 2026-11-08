"""Feature learn for Ask the Net (doc/AI_TOOL_CHAIN.md §49).

``propose_feature_learn`` is a proposal, never an execution. The model names a feature from a closed
set; the commands come from the reviewed catalogue (``learn/catalogue.py``), are checked by the
read-only command policy again, and become the same signed ``device_command`` card as every other
device proposal. After the run the output is parsed per command (Genie when the user may use it), so
the model reads the parsed handle; the playbook ``learn-ospf-of-a-device`` says how.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from services.ai_assistant.command_policy import (
    MAX_SIGNED_COMMANDS,
    CommandNotAllowedError,
    check_commands,
)
from services.ai_assistant.device_access import (
    DeviceAccessError,
    DeviceResolver,
    netmiko_device_type,
)
from services.ai_assistant.learn import catalogue
from services.ai_assistant.neighbors.catalogue import family_of
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.device_tools import (
    DEVICE_RESOLVER_KEY,
    GENIE_PARSER_KEY,
    make_device_proposal,
)

DeviceName = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9._-]{1,100}$")
]


class ProposeFeatureLearnInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device: DeviceName = Field(description="Device name exactly as in the inventory, e.g. 'LAB'")
    feature: Literal["ospf", "bgp"] = Field(
        description=(
            "The feature to learn: 'ospf' (process, areas, interfaces, neighbours, LSDB) or "
            "'bgp' (address families, neighbours and their state, templates, dampening)"
        )
    )


async def _propose(ctx: ToolContext, args: ProposeFeatureLearnInput) -> ToolOutput:
    resolver: DeviceResolver = ctx.extras[DEVICE_RESOLVER_KEY]
    try:
        device = await resolver.resolve(args.device)
    except DeviceAccessError as exc:
        return ToolOutput(str(exc), is_error=True)
    family = family_of(netmiko_device_type(device.network_driver, device.platform))
    try:
        plan = catalogue.plan_learn(family, args.feature)
        commands = check_commands(list(plan.commands), limit=MAX_SIGNED_COMMANDS)
    except (catalogue.UnsupportedLearnError, CommandNotAllowedError) as exc:
        return ToolOutput(f"Not possible: {exc}", is_error=True)
    genie = GENIE_PARSER_KEY in ctx.extras
    parser = "genie" if genie else "none"
    purpose = (
        f"These {len(commands)} commands come from a reviewed list that learns '{plan.feature}'. "
        f"Follow the playbook learn-{plan.feature}-of-a-device to read the result. "
    )
    if not genie:
        purpose += (
            "Genie is not available for this user, so the output is not parsed: read the raw "
            "handle with fetch_slice and say that the values come from unparsed text."
        )
    return make_device_proposal(ctx, device, commands, parser, purpose=purpose)


_DESCRIPTION = (
    "Ask the user to run the read-only commands that learn one feature of a device: 'ospf' "
    "(process, areas, interfaces, neighbours, database) or 'bgp' (address families, neighbours, "
    "sessions). The commands come from a reviewed list, you never write them. This only "
    "proposes: nothing runs until the user confirms in the card. Use it for 'learn OSPF/BGP of X' "
    "or 'show me the BGP state of X'; for one value use propose_device_command."
)


def build_learn_tools() -> list[Tool]:
    return [Tool("propose_feature_learn", _DESCRIPTION, ProposeFeatureLearnInput, _propose)]
