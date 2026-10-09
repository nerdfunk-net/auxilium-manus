"""Certificate uploads are bounded without buffering the whole body (S15)."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from fastapi import UploadFile

from services.certificates.certificate_service import MAX_CERT_UPLOAD_BYTES, CertificateService

_PEM = b"-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"


def _upload(content: bytes, name: str = "ca.crt") -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=name)


class CertificateUploadLimitTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.service = CertificateService(Path(self._tmp.name) / "c", Path(self._tmp.name) / "s")

    async def test_upload_over_64k_rejected(self) -> None:
        content = _PEM + b"#" * (MAX_CERT_UPLOAD_BYTES - len(_PEM) + 1)
        self.assertEqual(len(content), MAX_CERT_UPLOAD_BYTES + 1)
        with self.assertRaisesRegex(ValueError, "larger than 64 KiB"):
            await self.service.upload(_upload(content))

    async def test_upload_exactly_64k_ok(self) -> None:
        content = _PEM + b"#" * (MAX_CERT_UPLOAD_BYTES - len(_PEM))
        self.assertEqual(len(content), MAX_CERT_UPLOAD_BYTES)
        info = await self.service.upload(_upload(content))
        self.assertTrue(info.filename.endswith(".crt"))
