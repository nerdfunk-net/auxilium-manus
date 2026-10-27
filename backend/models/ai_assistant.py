from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

AiProvider = Literal["anthropic", "gemini", "openai_compat"]
AiStatusReason = Literal[
    "ok", "no_permission", "disabled", "not_configured", "operator_disabled", "provider_not_allowed"
]


class UserAiSettingsUpdate(BaseModel):
    """Partial update: omitted fields are left unchanged. ``api_key`` is write-only."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    provider: AiProvider | None = None
    model: str | None = Field(default=None, max_length=128)
    # Only meaningful for provider "openai_compat". An empty string clears it.
    base_url: str | None = Field(default=None, max_length=512)
    api_key: SecretStr | None = Field(default=None, min_length=1, max_length=512)
    clear_api_key: bool = False
    share_inventory_data: bool | None = None
    share_device_addresses: bool | None = None
    share_custom_fields: bool | None = None
    share_config_context: bool | None = None
    share_content_data: bool | None = None
    share_report_data: bool | None = None

    @field_validator("model")
    @classmethod
    def _model_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        # Control characters would forge lines in the audit log; the name is also length-capped.
        stripped = "".join(ch for ch in value if ch.isprintable()).strip()
        if not stripped:
            raise ValueError("model must not be blank")
        return stripped[:100]


class AiModelOption(BaseModel):
    id: str
    label: str
    description: str


class UserAiSettingsResponse(BaseModel):
    """What the owner may read back. The key itself is never returned, only ``api_key_set``."""

    enabled: bool
    provider: AiProvider
    model: str
    base_url: str | None
    api_key_set: bool
    # Ready to use: a key (anthropic, gemini) or a base URL + model (openai_compat).
    configured: bool
    share_inventory_data: bool
    share_device_addresses: bool
    share_custom_fields: bool
    share_config_context: bool
    share_content_data: bool
    share_report_data: bool
    available_providers: list[AiProvider]
    # Selectable models per provider; the UI shows a picker, not a free-text field.
    available_models: dict[str, list[AiModelOption]]
    # What the operator allows (AI_ASSISTANT_ENABLED / AI_ALLOWED_PROVIDERS / AI_ALLOWED_DATA);
    # the settings page greys out the rest. No secrets.
    operator_enabled: bool = True
    operator_providers: list[str] = Field(default_factory=list)
    operator_data: list[str] = Field(default_factory=list)


class AiStatusResponse(BaseModel):
    available: bool
    reason: AiStatusReason


class ChatMessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)


class EditorVariableIn(BaseModel):
    """A variable row from the template editor. ``is_auto`` marks device/run-derived variables;
    their values are never sent to the model (doc/ai_integration/AI_ASSISTANT.md §9b)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    type: str = Field(default="custom", max_length=50)
    value: str = Field(default="", max_length=50000)
    is_auto: bool = False


class TemplateEditorContext(BaseModel):
    """Current (possibly unsaved) state of the template editor, sent with each chat turn."""

    model_config = ConfigDict(extra="forbid")

    surface: Literal["template_editor"]
    name: str = Field(default="", max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    template_type: Literal["jinja2", "text", "textfsm"] = "jinja2"
    # "report": rendered once per report snapshot into Markdown, not once per device.
    category: Literal["netmiko", "report"] = "netmiko"
    content: str = Field(default="", max_length=200000)
    variables: list[EditorVariableIn] = Field(default_factory=list, max_length=200)


MAX_CANVAS_JSON_CHARS = 3_000_000


class WorkflowCanvasContext(BaseModel):
    """Current (possibly unsaved) workflow builder canvas, in the persisted shape."""

    model_config = ConfigDict(extra="forbid")

    surface: Literal["workflow_editor"]
    name: str = Field(default="", max_length=255)
    canvas_nodes: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    canvas_edges: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)
    canvas_groups: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    static_attributes: list[dict[str, Any]] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def _bounded_size(self) -> WorkflowCanvasContext:
        size = len(
            json.dumps(
                [self.canvas_nodes, self.canvas_edges, self.canvas_groups, self.static_attributes],
                default=str,
            )
        )
        if size > MAX_CANVAS_JSON_CHARS:
            raise ValueError("The canvas is too large to send to the assistant")
        return self


class RunViewerContext(BaseModel):
    """The workflow runs page: which run (if any) the user has open. Read-only surface."""

    model_config = ConfigDict(extra="forbid")

    surface: Literal["run_viewer"]
    run_id: int | None = Field(default=None, ge=1)


MAX_FILTER_JSON_CHARS = 100_000


class InventoryContext(BaseModel):
    """The inventory page: its Nautobot source and the filter currently in the builder.

    Read and propose only: the assistant never saves an inventory.
    """

    model_config = ConfigDict(extra="forbid")

    surface: Literal["inventory"]
    source_id: str = Field(min_length=1, max_length=64)
    # The builder's (possibly unsaved) condition tree, as the client holds it. Untrusted: the
    # server only renders it, bounded, and only to a model the user shares inventory data with.
    filter_tree: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _bounded_filter(self) -> InventoryContext:
        if self.filter_tree is not None and (
            len(json.dumps(self.filter_tree, default=str)) > MAX_FILTER_JSON_CHARS
        ):
            raise ValueError("The current filter is too large to send to the assistant")
        return self


class ReportsContext(BaseModel):
    """The reports page: which report source it is using. Read-only surface."""

    model_config = ConfigDict(extra="forbid")

    surface: Literal["reports"]
    source_id: str = Field(default="report_data", min_length=1, max_length=64)


AssistantContext = Annotated[
    TemplateEditorContext
    | WorkflowCanvasContext
    | RunViewerContext
    | InventoryContext
    | ReportsContext,
    Field(discriminator="surface"),
]


class ChatRequest(BaseModel):
    """Stateless chat turn: the client holds the history and re-sends it (v1)."""

    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessageIn] = Field(min_length=1, max_length=50)
    context: AssistantContext | None = None


class AiProxySettingsUpdate(BaseModel):
    """Full replacement of the global AI proxy settings (admin only)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    url: str = Field(default="", max_length=512)
    # A global "Basic Auth" (generic) credential; omitted for a proxy without authentication.
    credential_id: int | None = Field(default=None, ge=1)
    # Hosts that skip the proxy: a name, a domain suffix (corp.example) or a CIDR (10.0.0.0/8).
    bypass_hosts: list[Annotated[str, Field(min_length=1, max_length=255)]] = Field(
        default_factory=list, max_length=50
    )

    @field_validator("url")
    @classmethod
    def _strip_url(cls, value: str) -> str:
        return value.strip()

    @field_validator("bypass_hosts")
    @classmethod
    def _clean_hosts(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in values:
            entry = raw.strip().lower()
            if not entry or not all(ch.isalnum() or ch in "-._*:/" for ch in entry):
                raise ValueError("bypass_hosts entries may contain only letters, digits and -._*:/")
            if entry not in cleaned:
                cleaned.append(entry)
        return cleaned


class AiProxySettingsResponse(BaseModel):
    """The proxy password never leaves the credential store; only the credential reference does."""

    enabled: bool
    url: str
    credential_id: int | None
    credential_name: str | None
    bypass_hosts: list[str]
    # Ready to use: enabled with a URL.
    configured: bool
