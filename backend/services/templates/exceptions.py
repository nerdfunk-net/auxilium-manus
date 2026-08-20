"""Domain exceptions for the templates service."""

from __future__ import annotations


class TemplateError(Exception):
    """Base class for template domain errors."""


class TemplateNotFoundError(TemplateError):
    def __init__(self, template_id: int) -> None:
        super().__init__(f"Template with ID {template_id} not found")
        self.template_id = template_id


class TemplateNameConflictError(TemplateError):
    def __init__(self, name: str) -> None:
        super().__init__(f"A template named '{name}' already exists")
        self.name = name


class TemplateCredentialNotFoundError(TemplateError):
    def __init__(self, credential_id: int) -> None:
        super().__init__(f"Credential {credential_id} not found")
        self.credential_id = credential_id
