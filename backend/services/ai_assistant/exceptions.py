"""Errors raised by the in-app AI assistant services (doc/ai_integration/AI_ASSISTANT.md)."""

from __future__ import annotations


class AiAssistantError(Exception):
    """Base class; ``code`` is the stable machine-readable identifier sent to clients."""

    code = "ai_assistant_error"


class AiSettingsValidationError(AiAssistantError):
    code = "ai_settings_invalid"


class AiAssistantDisabledError(AiAssistantError):
    """The user's master switch is off. Enforced server-side; hiding the UI is a convenience."""

    code = "ai_assistant_disabled"


class AiAssistantNotConfiguredError(AiAssistantError):
    """The assistant is enabled but has no usable provider configuration (e.g. no API key)."""

    code = "ai_assistant_not_configured"


class AiConversationNotFoundError(AiAssistantError):
    """No saved conversation with this id for this user (another user's looks the same)."""

    code = "ai_conversation_not_found"


class AiConversationLimitError(AiAssistantError):
    """The user already holds the maximum number of saved conversations."""

    code = "ai_conversation_limit"


class AiConversationTooLargeError(AiAssistantError):
    code = "ai_conversation_too_large"
