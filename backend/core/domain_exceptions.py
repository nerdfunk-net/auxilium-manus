from __future__ import annotations


class DomainError(Exception):
    """Business error mapped to a 4xx HTTP response by the FastAPI handler."""

    status_code: int = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFoundError(DomainError):
    status_code = 404


class AccessDeniedError(DomainError):
    status_code = 403


class ConflictError(DomainError):
    status_code = 409


class ValidationFailedError(DomainError):
    status_code = 400
