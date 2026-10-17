"""Minimum lengths for stored and generated secrets (S3-15), in one place."""

from __future__ import annotations

# A credential password / token: device secrets may be short, but not below the floor under which
# the run-scoped redaction registry would not track the value at all.
MIN_PASSWORD_LENGTH = 8
# The passphrase of a ``shared_secret`` credential (the key of the AM2 encrypt/decrypt steps).
MIN_SHARED_SECRET_LENGTH = 12
# What ``secret-generate`` may produce.
MIN_GENERATED_SECRET_LENGTH = 12
