"""Tests for StepRunner._serialize_outcomes secret redaction (H1-D)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from core.crypto import EncryptionService
from models.workflow_context import Capability, DeviceContext, DeviceStatus, StepOutcome, WorkflowContext
from services.execution.step_runner import StepRunner
from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER, seal_secret

_ENC = EncryptionService("test-secret-key-for-step-runner")


@patch.dict(os.environ, {"CREDENTIAL_ENCRYPTION_KEY": "test-secret-key-for-step-runner"})
class SerializeOutcomesRedactionTests(unittest.TestCase):
    def test_persisted_output_has_placeholder_not_cleartext_or_ciphertext(self) -> None:
        sealed = seal_secret("s3cr3t", encryption=_ENC)
        device = DeviceContext(
            id="dev-1",
            name="lab",
            hostname="lab",
            attribute_bags={"tacacs": {"shared_secret": sealed}},
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"dev-1": device})
        outcomes = [StepOutcome(name="success", context=context)]

        persisted = StepRunner._serialize_outcomes(outcomes)

        leaf = persisted["outcomes"]["success"]["devices"]["dev-1"]["attribute_bags"]["tacacs"][
            "shared_secret"
        ]
        self.assertEqual(leaf, REDACTED_PLACEHOLDER)
        self.assertNotIn("s3cr3t", str(persisted))
        self.assertNotIn(sealed["ct"], str(persisted))

    def test_in_memory_context_object_stays_sealed(self) -> None:
        """_serialize_outcomes must not mutate the StepOutcome it's given —
        callers keep passing the sealed, decryptable context to later steps."""
        sealed = seal_secret("s3cr3t", encryption=_ENC)
        device = DeviceContext(
            id="dev-1",
            name="lab",
            hostname="lab",
            attribute_bags={"tacacs": {"shared_secret": sealed}},
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={"dev-1": device})
        outcomes = [StepOutcome(name="success", context=context)]

        StepRunner._serialize_outcomes(outcomes)

        still_sealed = outcomes[0].context.devices["dev-1"].attribute_bags["tacacs"]["shared_secret"]
        self.assertEqual(still_sealed, sealed)


if __name__ == "__main__":
    unittest.main()
