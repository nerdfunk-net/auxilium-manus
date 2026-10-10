from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

AiProvider = Literal["anthropic", "gemini", "openai_compat"]
AiStatusReason = Literal["ok", "no_permission", "disabled", "not_configured"]


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
    share_content_data: bool | None = None

    @field_validator("model")
    @classmethod
    def _model_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("model must not be blank")
        return stripped


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
    share_content_data: bool
    available_providers: list[AiProvider]
    # Selectable models per provider; the UI shows a picker, not a free-text field.
    available_models: dict[str, list[AiModelOption]]


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
    content: str = Field(default="", max_length=200000)
    variables: list[EditorVariableIn] = Field(default_factory=list, max_length=200)


class ChatRequest(BaseModel):
    """Stateless chat turn: the client holds the history and re-sends it (v1)."""

    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessageIn] = Field(min_length=1, max_length=50)
    context: TemplateEditorContext | None = None
