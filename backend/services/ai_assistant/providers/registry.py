"""Provider lookup. The only place that knows which adapter backs which provider id."""

from __future__ import annotations

from services.ai_assistant.exceptions import AiSettingsValidationError
from services.ai_assistant.providers.anthropic_provider import AnthropicProvider
from services.ai_assistant.providers.base import LlmProvider


def build_provider(provider: str, *, api_key: str, base_url: str | None) -> LlmProvider:
    if provider == "anthropic":
        return AnthropicProvider(api_key)
    raise AiSettingsValidationError(f"Provider {provider!r} is not available")
