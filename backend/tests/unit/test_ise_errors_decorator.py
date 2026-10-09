"""routers.sources.ise.errors.ise_errors maps ISE failures uniformly (Q2)."""

from __future__ import annotations

import unittest

from fastapi import HTTPException

from routers.sources.ise.errors import ise_errors
from services.ise.common.exceptions import ISEAPIError, ISENotFoundError, ISEValidationError


def _raising(exc: BaseException):
    @ise_errors("do thing")
    async def handler() -> None:
        raise exc

    return handler


class IseErrorsTests(unittest.IsolatedAsyncioTestCase):
    async def test_maps_status(self) -> None:
        cases = [
            (ISENotFoundError("ISE resource not found: /ers/config/secret-path"), 404),
            (ISEValidationError("bad"), 400),
            (ISEAPIError("upstream secret text"), 502),
            (RuntimeError("internal secret text"), 500),
        ]
        for exc, status in cases:
            with self.subTest(exc=type(exc).__name__):
                with self.assertRaises(HTTPException) as caught:
                    await _raising(exc)()
                self.assertEqual(caught.exception.status_code, status)
                if status in (404, 502, 500):
                    self.assertNotIn("secret", str(caught.exception.detail))
                    self.assertNotIn("/ers/", str(caught.exception.detail))

    async def test_http_exception_passes_through_and_result_returned(self) -> None:
        passthrough = HTTPException(status_code=418, detail="teapot")
        with self.assertRaises(HTTPException) as caught:
            await _raising(passthrough)()
        self.assertIs(caught.exception, passthrough)

        @ise_errors("ok")
        async def fine(value: int) -> int:
            return value + 1

        self.assertEqual(await fine(1), 2)
