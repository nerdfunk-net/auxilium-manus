"""Per-surface assembly: which tools a chat turn gets and what the model is told up front.

Surfaces send their *current* client-side state; the server decides what of it the model may see
(doc/ai_integration/AI_ASSISTANT.md §9b) and redacts it before building the prompt.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from models.ai_assistant import (
    MAX_CANVAS_JSON_CHARS,
    InventoryContext,
    ReportsContext,
    RunViewerContext,
    TemplateEditorContext,
    WorkflowCanvasContext,
)
from services.ai_assistant.agent_loop import DEFAULT_BUDGET, RunBudget
from services.ai_assistant.client_data_reader import ClientDataReader
from services.ai_assistant.config_backup import ConfigBackupReader
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.device_access import DeviceResolver
from services.ai_assistant.inventory_filter import describe_condition_tree, field_data_class
from services.ai_assistant.output_parser import GenieParser
from services.ai_assistant.prompts import (
    ACI_PROMPT,
    BASE_SYSTEM_PROMPT,
    CATALYST_PROMPT,
    CLIENT_DATA_PROMPT,
    CONFIG_BACKUP_PROMPT,
    DEVICE_COMMANDS_PROMPT,
    HOST_LOOKUP_PROMPT,
    INVENTORY_PROMPT,
    NAUTOBOT_PROMPT,
    NEIGHBOR_PROMPT,
    RELEASED_WORKFLOWS_PROMPT,
    REPORT_TEMPLATE_PROMPT,
    REPORTS_PROMPT,
    RUN_EXPLAIN_PROMPT,
    RUN_VIEWER_PROMPT,
    TEMPLATE_EDITOR_PROMPT,
    WORKFLOW_EDITOR_PROMPT,
    general_prompt,
)
from services.ai_assistant.redaction import MAX_REDACT_CHARS_PER_REQUEST, Redactor
from services.ai_assistant.released_workflow_reader import ReleasedWorkflowReader
from services.ai_assistant.results.store import ResultStore
from services.ai_assistant.tools.aci_tools import ACI_READER_KEY, AciReader, build_aci_tools
from services.ai_assistant.tools.base import Toolbox, ToolContext
from services.ai_assistant.tools.batfish_tools import (
    BATFISH_READER_KEY,
    BatfishReader,
    build_batfish_tools,
)
from services.ai_assistant.tools.catalyst_center_tools import (
    CATALYST_READER_KEY,
    CatalystReader,
    build_catalyst_center_tools,
)
from services.ai_assistant.tools.client_data_tools import (
    CLIENT_DATA_READER_KEY,
    build_client_data_tools,
)
from services.ai_assistant.tools.config_backup_tools import (
    CONFIG_READER_KEY,
    build_config_backup_tools,
)
from services.ai_assistant.tools.device_name_tools import build_device_name_tools
from services.ai_assistant.tools.device_tools import (
    DEVICE_RESOLVER_KEY,
    GENIE_PARSER_KEY,
    build_device_tools,
)
from services.ai_assistant.tools.glossary_tools import (
    GLOSSARY_TOOLS,
    STEP_ALIAS_TOOLS,
    StepAliasLookup,
)
from services.ai_assistant.tools.host_lookup_tools import build_host_lookup_tools
from services.ai_assistant.tools.inventory_filter_tools import INVENTORY_FILTER_TOOLS
from services.ai_assistant.tools.inventory_tools import (
    INVENTORY_TOOLS,
    InventoryReader,
    InventoryState,
)
from services.ai_assistant.tools.nautobot_tools import (
    NAUTOBOT_READER_KEY,
    NautobotQueryReader,
    build_nautobot_tools,
)
from services.ai_assistant.tools.neighbor_tools import (
    build_neighbor_live_tools,
    build_neighbor_read_tools,
)
from services.ai_assistant.tools.output_parse_tools import build_output_parse_tools
from services.ai_assistant.tools.playbook_tools import AVAILABLE_TOOLS_KEY, build_playbook_tools
from services.ai_assistant.tools.released_workflow_tools import (
    RELEASED_WORKFLOWS_KEY,
    build_released_workflow_tools,
)
from services.ai_assistant.tools.report_tools import REPORT_TOOLS, ReportReader, ReportsState
from services.ai_assistant.tools.result_tools import RESULT_STORE_KEY, build_result_tools
from services.ai_assistant.tools.run_tools import (
    RUN_LOOKUP_TOOLS,
    RUN_VIEWER_TOOLS,
    RunReader,
    run_viewer_extras,
)
from services.ai_assistant.tools.template_tools import (
    TEMPLATE_EDITOR_TOOLS,
    TemplateEditorState,
    TemplateReader,
)
from services.ai_assistant.tools.workflow_tools import (
    WORKFLOW_EDITOR_TOOLS,
    PluginCatalogue,
    ReferenceReader,
    WorkflowEditorState,
    WorkflowValidator,
)
from services.ai_assistant.workflow_expand import build_compact_view

MAX_VARIABLE_VALUE_CHARS = 1000

# Ask the Net chains discovery, query and result tools, so it gets more steps than the editors.
# The token figure counts input re-sent on every step; the time figure is wall clock per question.
# 300 s: a local model is much slower than a hosted one, and every step re-sends the conversation.
# Where the time goes is logged per question (``agent_loop``: model vs tool seconds).
GENERAL_BUDGET = RunBudget(max_tool_steps=16, max_total_tokens=400_000, max_seconds=300)


@dataclass(frozen=True)
class AssistantSession:
    system: str
    toolbox: Toolbox
    budget: RunBudget = DEFAULT_BUDGET


def _editor_state_block(context: TemplateEditorContext, redactor: Redactor) -> str:
    custom = [v for v in context.variables if not v.is_auto]
    withheld = [v.name for v in context.variables if v.is_auto]
    variable_lines = [
        f"- {v.name} ({v.type}) = {redactor.redact(v.value[:MAX_VARIABLE_VALUE_CHARS])}"
        for v in custom
    ]
    return (
        "<editor_state>\n"
        f"template name: {redactor.redact(context.name) or '(unsaved)'}\n"
        f"type: {context.template_type}\n"
        f"category: {context.category}\n"
        f"description: {redactor.redact(context.description or '')}\n"
        "custom variables (user-defined, values shown):\n"
        f"{chr(10).join(variable_lines) or '(none)'}\n"
        "device/run variables present in the editor (values withheld): "
        f"{', '.join(withheld) or '(none)'}\n"
        "<content>\n"
        f"{redactor.redact(context.content)}\n"
        "</content>\n"
        "</editor_state>"
    )


def build_template_editor_session(
    *,
    user_id: int,
    context: TemplateEditorContext,
    reader: TemplateReader,
    known_secrets: Iterable[str] = (),
) -> AssistantSession:
    redactor = Redactor()
    redactor.add_known_secrets(known_secrets)
    state = TemplateEditorState(context=context, reader=reader)
    tool_context = ToolContext(
        user_id=user_id, redactor=redactor, extras={"template_editor": state}
    )
    # The state block is built first so its secrets get tokens before any tool runs.
    prompts = [BASE_SYSTEM_PROMPT, TEMPLATE_EDITOR_PROMPT]
    if context.category == "report":
        prompts.append(REPORT_TEMPLATE_PROMPT)
    system = "\n\n".join([*prompts, _editor_state_block(context, redactor)])
    return AssistantSession(system=system, toolbox=Toolbox(TEMPLATE_EDITOR_TOOLS, tool_context))


def build_workflow_editor_session(
    *,
    user_id: int,
    context: WorkflowCanvasContext,
    registry: PluginCatalogue,
    references: ReferenceReader,
    validator: WorkflowValidator,
    may_propose: bool = True,
    glossary: StepAliasLookup | None = None,
) -> AssistantSession:
    # The canvas may be up to MAX_CANVAS_JSON_CHARS of JSON; its strings are redacted one by one.
    redactor = Redactor(max_chars=max(MAX_REDACT_CHARS_PER_REQUEST, MAX_CANVAS_JSON_CHARS))
    state = WorkflowEditorState(
        nodes=context.canvas_nodes,
        edges=context.canvas_edges,
        groups=context.canvas_groups,
        static_attributes=context.static_attributes,
        registry=registry,
        references=references,
        validator=validator,
    )
    extras: dict[str, Any] = {"workflow_editor": state}
    if glossary is not None:
        extras["glossary"] = glossary
    tool_context = ToolContext(user_id=user_id, redactor=redactor, extras=extras)
    # Built first so secrets in step configs get their tokens before any tool runs.
    view = build_compact_view(
        context.canvas_nodes, context.canvas_edges, context.static_attributes, redactor
    )
    canvas_block = (
        "<canvas_state>\n"
        f"workflow name: {redactor.redact(context.name) or '(unsaved)'}\n"
        f"{json.dumps(view, default=str)}\n"
        "</canvas_state>"
    )
    system = "\n\n".join([BASE_SYSTEM_PROMPT, WORKFLOW_EDITOR_PROMPT, canvas_block])
    # A user without ``workflows:write`` can still be advised, but gets no proposal tool (S5-08).
    tools = tuple(t for t in WORKFLOW_EDITOR_TOOLS if may_propose or t.name != "propose_workflow")
    if glossary is not None:
        tools = (*tools, *STEP_ALIAS_TOOLS)
    return AssistantSession(system=system, toolbox=Toolbox(tools, tool_context))


def build_run_viewer_session(
    *,
    user_id: int,
    context: RunViewerContext,
    reader: RunReader,
    sharing: SharingPolicy,
    known_secrets: Iterable[str] = (),
) -> AssistantSession:
    redactor = Redactor()
    redactor.add_known_secrets(known_secrets)
    tool_context = ToolContext(
        user_id=user_id,
        redactor=redactor,
        extras=run_viewer_extras(reader, sharing, context.run_id),
        sharing=sharing,
    )
    opened = (
        f"The user has run {context.run_id} open."
        if context.run_id is not None
        else "No run is open; ask which run (id) to look at."
    )
    sharing_line = f"Data the user shares with you: {sharing.describe()}."
    system = "\n\n".join([BASE_SYSTEM_PROMPT, RUN_VIEWER_PROMPT, opened, sharing_line])
    return AssistantSession(system=system, toolbox=Toolbox(RUN_VIEWER_TOOLS, tool_context))


def build_inventory_session(
    *,
    user_id: int,
    context: InventoryContext,
    reader: InventoryReader,
    sharing: SharingPolicy,
    may_propose: bool = True,
) -> AssistantSession:
    tool_context = ToolContext(
        user_id=user_id,
        redactor=Redactor(),
        extras={"inventory": InventoryState(reader=reader)},
        sharing=sharing,
    )
    shared = sharing.describe() if sharing.inventory else "nothing about individual devices"
    system = "\n\n".join(
        [
            BASE_SYSTEM_PROMPT,
            INVENTORY_PROMPT,
            f"Data the user shares with you: {shared}.",
            _current_filter_block(context, tool_context.redactor, sharing),
        ]
    )
    # Saving an inventory needs sources.nautobot:write; without it the user could not keep a
    # proposal, so the tool is not offered (the workflow surface does the same).
    filter_tools = tuple(
        t for t in INVENTORY_FILTER_TOOLS if may_propose or t.name != "propose_inventory"
    )
    if not may_propose:
        system += (
            "\n\nThe user may not save inventories, so you cannot propose one: you can still "
            "preview a filter to answer how many devices it would select."
        )
    toolbox = Toolbox((*INVENTORY_TOOLS, *filter_tools, *GLOSSARY_TOOLS), tool_context)
    return AssistantSession(system=system, toolbox=toolbox)


def _current_filter_block(
    context: InventoryContext, redactor: Redactor, sharing: SharingPolicy
) -> str:
    """What is in the builder now. Condition values can be device names, so they are class B."""
    tree = context.filter_tree
    items = tree.get("items") if isinstance(tree, dict) else None
    if not isinstance(items, list) or not items:
        return "The inventory builder's current filter is empty."
    if not sharing.inventory:
        return (
            f"The inventory builder's current filter has {len(items)} condition(s) or group(s); "
            "their contents are not shared with you."
        )
    # Prefix and custom-field values are addresses / possibly secrets: their own switches apply.
    described = redactor.redact(
        describe_condition_tree(
            tree, hide=lambda field: not sharing.allows(field_data_class(field))
        )
    )
    return (
        "<current_filter>\nThe inventory builder's current (maybe unsaved) filter:\n"
        f"{described}\n</current_filter>"
    )


def build_reports_session(
    *,
    user_id: int,
    context: ReportsContext,
    reader: ReportReader,
    sharing: SharingPolicy,
) -> AssistantSession:
    tool_context = ToolContext(
        user_id=user_id,
        redactor=Redactor(),
        extras={"reports": ReportsState(reader=reader, source_id=context.source_id)},
        sharing=sharing,
    )
    shared = "report values" if sharing.report_data else "no report values (only the catalog)"
    system = "\n\n".join(
        [BASE_SYSTEM_PROMPT, REPORTS_PROMPT, f"Data the user shares with you: {shared}."]
    )
    return AssistantSession(system=system, toolbox=Toolbox(REPORT_TOOLS, tool_context))


def build_general_session(
    *,
    user_id: int,
    reader: BatfishReader,
    store: ResultStore | None,
    sharing: SharingPolicy,
    may_query_batfish: bool,
    known_secrets: Iterable[str] = (),
    device_resolver: DeviceResolver | None = None,
    config_reader: ConfigBackupReader | None = None,
    nautobot_reader: NautobotQueryReader | None = None,
    catalyst_reader: CatalystReader | None = None,
    aci_reader: AciReader | None = None,
    run_reader: RunReader | None = None,
    released_reader: ReleasedWorkflowReader | None = None,
    genie_parser: GenieParser | None = None,
    client_data_reader: ClientDataReader | None = None,
) -> AssistantSession:
    """Ask the Net: read-only questions about the network (doc/AI_TOOL_CHAIN.md §10a, §20.3).

    The Batfish tools are offered only to a user who may query Batfish (the same permission the
    query endpoints need); the handle tools only when a result store exists. The Nautobot tools
    (DCIM / IPAM reads) are independent of Batfish: the router passes ``nautobot_reader`` when the
    user holds ``sources.nautobot:read``. No tool here writes,
    proposes or executes: pinned by ``test_ai_hardening``. The one exception is
    ``propose_device_command`` (doc/AI_TOOL_CHAIN.md §29), offered only when the router passes a
    ``device_resolver``, i.e. when the operator switch, the permission and the content opt-in all
    hold. It only proposes; the user's click runs it.
    """
    redactor = Redactor()
    redactor.add_known_secrets(known_secrets)
    extras: dict[str, Any] = {BATFISH_READER_KEY: reader}
    tools = []
    if may_query_batfish:
        tools.extend(build_batfish_tools())
        if store is not None:
            extras[RESULT_STORE_KEY] = store
            tools.extend(build_result_tools())
        # Playbooks only guide the Batfish tools, so they come with them; without the permission
        # the session has no tools at all.
        tools.extend(build_playbook_tools())
        tools.extend(build_neighbor_read_tools())
        if device_resolver is not None:
            extras[DEVICE_RESOLVER_KEY] = device_resolver
            tools.extend(build_device_tools())
            # Neighbour discovery (doc/AI_TOOL_CHAIN.md §24): the proposal sits with the device
            # tools; reading its result needs the result store.
            tools.extend(build_neighbor_live_tools(with_results=store is not None))
            # Parsing (doc/AI_TOOL_CHAIN.md §43): the parse tool reads stored outputs, so it needs
            # the store; Genie is offered only when the router found exactly one usable pyATS
            # source for this user.
            if store is not None:
                tools.extend(build_output_parse_tools())
            if genie_parser is not None:
                extras[GENIE_PARSER_KEY] = genie_parser
        # Backed-up configs from git (plan AI_CONFIG_FROM_GIT): content, so the router passes the
        # reader only with the opt-in and the repository read permission.
        if config_reader is not None:
            extras[CONFIG_READER_KEY] = config_reader
            tools.extend(build_config_backup_tools())
    # Documented inventory reads (doc/AI_TOOL_CHAIN.md, "Nautobot tools"). They do not need
    # Batfish, so they sit outside the Batfish branch.
    if nautobot_reader is not None:
        extras[NAUTOBOT_READER_KEY] = nautobot_reader
        tools.extend(build_nautobot_tools())
    # Cisco Catalyst Center reads (doc/AI_TOOL_CHAIN.md §42); independent of Batfish and Nautobot.
    if catalyst_reader is not None:
        extras[CATALYST_READER_KEY] = catalyst_reader
        tools.extend(build_catalyst_center_tools())
    # Cisco ACI reads (doc/plans/ACI_TOOL_CHAIN.md); independent of Batfish and Nautobot.
    if aci_reader is not None:
        extras[ACI_READER_KEY] = aci_reader
        tools.extend(build_aci_tools())
    # Collected client data (doc/CLIENT_DATA.md): stored observations, independent of Batfish.
    if client_data_reader is not None:
        extras[CLIENT_DATA_READER_KEY] = client_data_reader
        tools.extend(build_client_data_tools())
    # One question, two sources: find_host asks the client data and the APIC together. It is a
    # composition of find_client and find_aci_endpoint, so it needs both readers.
    if client_data_reader is not None and aci_reader is not None:
        tools.extend(build_host_lookup_tools())
    # Run explanations (plan: runs in Ask the Net): the run-viewer tools plus list_runs, shared
    # with the runs-page assistant. No run is open here, so every tool takes a run_id.
    if run_reader is not None:
        extras.update(run_viewer_extras(run_reader, sharing, can_list_runs=True))
        tools.extend((*RUN_VIEWER_TOOLS, *RUN_LOOKUP_TOOLS))
    # Released workflows (doc/AI_TOOL_CHAIN.md section 16): list/describe, one proposal, and the
    # result read. The result and status come from the run tools, so they need the run reader.
    if released_reader is not None and run_reader is not None:
        extras[RELEASED_WORKFLOWS_KEY] = released_reader
        tools.extend(build_released_workflow_tools())
    if may_query_batfish and nautobot_reader is not None:
        # The two systems name a device differently (config hostname vs full name); this is the
        # explicit lookup between them (doc/AI_TOOL_CHAIN.md §33). Only useful with both.
        tools.extend(build_device_name_tools())
    if may_query_batfish:
        # Lets list_playbooks tell the model which of a playbook's tools this user lacks.
        extras[AVAILABLE_TOOLS_KEY] = frozenset(t.name for t in tools)
    tool_context = ToolContext(user_id=user_id, redactor=redactor, extras=extras, sharing=sharing)
    parts = [
        BASE_SYSTEM_PROMPT,
        general_prompt(device_commands=device_resolver is not None and may_query_batfish),
        f"Data the user shares with you: {sharing.describe()}.",
    ]
    if device_resolver is not None and may_query_batfish:
        parts.append(DEVICE_COMMANDS_PROMPT)
        parts.append(NEIGHBOR_PROMPT)
    if config_reader is not None and may_query_batfish:
        parts.append(CONFIG_BACKUP_PROMPT)
    if nautobot_reader is not None:
        parts.append(NAUTOBOT_PROMPT)
    if catalyst_reader is not None:
        parts.append(CATALYST_PROMPT)
    if aci_reader is not None:
        parts.append(ACI_PROMPT)
    if client_data_reader is not None:
        parts.append(CLIENT_DATA_PROMPT)
        if aci_reader is not None:
            parts.append(HOST_LOOKUP_PROMPT)
    if run_reader is not None:
        parts.append(RUN_EXPLAIN_PROMPT)
    if released_reader is not None and run_reader is not None:
        parts.append(RELEASED_WORKFLOWS_PROMPT)
    if not may_query_batfish:
        offered = [
            name
            for name, reader_ in (
                ("Nautobot", nautobot_reader),
                ("Catalyst Center", catalyst_reader),
                ("ACI", aci_reader),
                ("client data", client_data_reader),
                ("run", run_reader),
            )
            if reader_ is not None
        ]
        if not offered:
            parts.append(
                "The user is not allowed to query Batfish, so you have no tools. Say so and "
                "answer only from general knowledge, without claiming anything about their "
                "network."
            )
        else:
            parts.append(
                "The user is not allowed to query Batfish, so you have only the "
                f"{' and '.join(offered)} tools. Say so where it matters."
                + (
                    " Nautobot shows what is documented, not how the network behaves."
                    if nautobot_reader is not None
                    else ""
                )
            )
    return AssistantSession(
        system="\n\n".join(parts),
        toolbox=Toolbox(tools, tool_context),
        # No tools, no reason for the larger budget.
        budget=GENERAL_BUDGET if tools else DEFAULT_BUDGET,
    )
