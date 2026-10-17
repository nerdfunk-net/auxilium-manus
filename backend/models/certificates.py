"""Pydantic models for the CA certificate manager (dev/admin tools)."""

from __future__ import annotations

from pydantic import BaseModel


class CertificateInfo(BaseModel):
    filename: str
    path: str
    size: int
    exists_in_system: bool


class ScanResponse(BaseModel):
    certificates: list[CertificateInfo]
    certs_directory: str


class AddCertificateRequest(BaseModel):
    filename: str


class AddCertificateResponse(BaseModel):
    success: bool
    message: str
    error: str | None = None
    command_output: str | None = None
