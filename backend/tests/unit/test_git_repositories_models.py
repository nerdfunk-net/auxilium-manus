"""Webhook-secret length rule on the git repository request models (W2)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.git_repositories import GitRepositoryRequest, GitRepositoryUpdateRequest

_BASE = {"name": "configs", "category": "device_configs", "url": "https://example.com/x.git"}


def test_short_webhook_secret_rejected_on_create() -> None:
    with pytest.raises(ValidationError):
        GitRepositoryRequest(**_BASE, webhook_secret="short")


def test_long_webhook_secret_accepted_on_create() -> None:
    assert GitRepositoryRequest(**_BASE, webhook_secret="x" * 16).webhook_secret == "x" * 16


def test_short_webhook_secret_rejected_on_update() -> None:
    with pytest.raises(ValidationError):
        GitRepositoryUpdateRequest(webhook_secret="short")


def test_empty_webhook_secret_clears_on_update() -> None:
    assert GitRepositoryUpdateRequest(webhook_secret="").webhook_secret == ""


def test_omitted_webhook_secret_keeps_on_update() -> None:
    assert GitRepositoryUpdateRequest().webhook_secret is None
