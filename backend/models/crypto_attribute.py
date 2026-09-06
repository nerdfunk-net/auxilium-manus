"""Request/response models for the encrypt-attribute / decrypt-attribute
editor "Test" APIs.

These endpoints are a stateless crypto calculator: the caller supplies both the
value and the shared secret, so nothing is read from or written to the vault.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class EncryptAttributeTestRequest(BaseModel):
    plaintext: str = Field(min_length=1)
    shared_secret: str = Field(min_length=1)
    algorithm: str | None = None


class EncryptAttributeTestResponse(BaseModel):
    ciphertext: str
    algorithm: str


class DecryptAttributeTestRequest(BaseModel):
    ciphertext: str = Field(min_length=1)
    shared_secret: str = Field(min_length=1)
    algorithm: str | None = None


class DecryptAttributeTestResponse(BaseModel):
    plaintext: str
    algorithm: str
