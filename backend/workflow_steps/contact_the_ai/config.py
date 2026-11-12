"""Defaults for the contact-the-ai step."""

DEFAULT_MAX_OUTPUT_TOKENS = 1024
MAX_OUTPUT_TOKENS_LIMIT = 4096
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_OUTPUT_ATTRIBUTE = "ai.response"
MAX_TIMEOUT_SECONDS = 600


def get_config() -> dict:
    return {
        "prompt": (
            "Summarize this workflow run for a chat notification in at most five short lines.\n"
            "{run_summary}"
        ),
        "system_prompt": "",
        "output_attribute": DEFAULT_OUTPUT_ATTRIBUTE,
        "max_output_tokens": DEFAULT_MAX_OUTPUT_TOKENS,
        "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
    }
