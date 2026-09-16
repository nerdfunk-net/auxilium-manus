"""Request/response models for the encrypt-attribute / decrypt-attribute
editor "Test" APIs.

The caller supplies the value plus exactly one shared-secret source:
``shared_secret`` (typed inline) or ``credential_reference`` (a
``shared_secret``-type credential name resolved server-side, same as the step
itself does at run time). Neither the typed secret nor a resolved
credential's passphrase is ever echoed back in the response.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class _SharedSecretSourceMixin(BaseModel):
    shared_secret: str | None = Field(default=None, min_length=1)
    credential_reference: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _exactly_one_secret_source(self) -> _SharedSecretSourceMixin:
        if bool(self.shared_secret) == bool(self.credential_reference):
            raise ValueError(
                "exactly one of shared_secret or credential_reference is required"
            )
        return self


class EncryptAttributeTestRequest(_SharedSecretSourceMixin):
    plaintext: str = Field(min_length=1)
    algorithm: str | None = None


class EncryptAttributeTestResponse(BaseModel):
    ciphertext: str
    algorithm: str


class DecryptAttributeTestRequest(_SharedSecretSourceMixin):
    ciphertext: str = Field(min_length=1)
    algorithm: str | None = None


class DecryptAttributeTestResponse(BaseModel):
    plaintext: str
    algorithm: str
