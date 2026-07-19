"""Tests for TemplatesService.render (sandboxed Jinja rendering)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from services.templates.templates_service import TemplatesService


class TemplatesServiceRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = TemplatesService(db=MagicMock())

    def test_renders_simple_variable(self) -> None:
        result = self.service.render(
            template_content="hostname {{ name }}", variables={"name": "r1"}
        )

        self.assertEqual(result["rendered_content"], "hostname r1")
        self.assertEqual(result["variables_used"], ["name"])
        self.assertEqual(result["warnings"], [])

    def test_undefined_variable_raises_value_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.service.render(template_content="{{ missing.value }}", variables={})

        self.assertIn("Undefined variable", str(ctx.exception))

    def test_syntax_error_raises_value_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            self.service.render(template_content="{% if %}", variables={})

        self.assertIn("syntax error", str(ctx.exception))

    def test_sandbox_blocks_unsafe_attribute_access(self) -> None:
        """SandboxedEnvironment rejects access to underscore-prefixed / unsafe
        attributes that unrestricted jinja2.Template would allow through,
        e.g. climbing the class hierarchy via __class__.__mro__."""
        with self.assertRaises(ValueError) as ctx:
            self.service.render(
                template_content="{{ ''.__class__.__mro__[1].__subclasses__() }}",
                variables={},
            )

        self.assertIn("disallowed construct", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
