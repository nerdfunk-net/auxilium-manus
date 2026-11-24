"""Tests for Jinja rendering helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from jinja2.sandbox import SandboxedEnvironment

from models.workflow_context import Capability, DeviceContext, DeviceStatus
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.common.jinja_render import (
    JinjaTemplateError,
    build_jinja_context,
    render_jinja_template,
    template_variables,
    validate_jinja_template,
)


class JinjaRenderParseTests(unittest.TestCase):
    """W3a-15: a render parses the template once, and keeps the validator's errors."""

    def test_a_render_parses_the_template_once(self) -> None:
        calls: list[str] = []
        original = SandboxedEnvironment._parse

        def _counting(self, source, name, filename):  # noqa: ANN001, ANN202
            calls.append(source)
            return original(self, source, name, filename)

        with patch.object(SandboxedEnvironment, "_parse", _counting):
            self.assertEqual(render_jinja_template("a {{ v }}", {"v": 1}), "a 1")

        self.assertEqual(len(calls), 1)

    def test_a_syntax_error_is_reported_like_the_validator_does(self) -> None:
        template = "ok\n{% if %}"
        with self.assertRaises(JinjaTemplateError) as validated:
            validate_jinja_template(template)
        with self.assertRaises(JinjaTemplateError) as rendered:
            render_jinja_template(template, {})

        self.assertEqual(str(rendered.exception), str(validated.exception))
        self.assertEqual(rendered.exception.failure, validated.exception.failure)
        assert rendered.exception.failure is not None
        self.assertEqual(rendered.exception.failure.kind, "template_syntax")
        self.assertEqual(rendered.exception.failure.line, 2)

    def test_the_syntax_error_line_counts_the_blank_lines_before_the_template(self) -> None:
        with self.assertRaises(JinjaTemplateError) as rendered:
            render_jinja_template("\n\nok\n{% if %}", {})

        assert rendered.exception.failure is not None
        self.assertEqual(rendered.exception.failure.line, 4)

    def test_an_empty_template_is_reported_like_the_validator_does(self) -> None:
        with self.assertRaises(JinjaTemplateError) as validated:
            validate_jinja_template("  \n ")
        with self.assertRaises(JinjaTemplateError) as rendered:
            render_jinja_template("  \n ", {})

        self.assertEqual(str(rendered.exception), "Template is empty")
        self.assertEqual(rendered.exception.failure, validated.exception.failure)


class TemplateVariablesTests(unittest.TestCase):
    def test_lists_the_top_level_names_read_from_the_context(self) -> None:
        template = "{{ device.name }} {% for c in commands %}{{ c.raw }}{% endfor %}"

        self.assertEqual(template_variables(template), {"device", "commands"})

    def test_a_locally_declared_name_is_not_a_context_variable(self) -> None:
        self.assertEqual(template_variables("{% set command = 1 %}{{ command }}"), frozenset())

    def test_a_syntax_error_yields_no_names(self) -> None:
        self.assertEqual(template_variables("{% if %}"), frozenset())


class JinjaRenderTests(unittest.TestCase):
    def test_validate_rejects_empty_template(self) -> None:
        with self.assertRaises(JinjaTemplateError):
            validate_jinja_template("   ")

    def test_render_device_template_with_namespaces(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            network_driver="cisco_ios",
            attribute_bags={"nautobot": {"role": {"name": "access-switch"}}},
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )
        context = build_jinja_context(
            device,
            run_id="run-1",
            workflow_id="wf-1",
        )
        rendered = render_jinja_template(
            "hostname {{ device.hostname }}\nrole {{ nautobot.role.name }}",
            context,
        )
        self.assertIn("hostname lab", rendered)
        self.assertIn("role access-switch", rendered)

    def test_render_fails_on_undefined_variable(self) -> None:
        with self.assertRaises(JinjaTemplateError):
            render_jinja_template("{{ missing.value }}", {"device": {"name": "lab"}})

    def test_sealed_secrets_inside_a_list_are_unwrapped_for_the_template(self) -> None:
        device = DeviceContext(
            id="device-1",
            name="lab",
            hostname="lab",
            attribute_bags={
                "nautobot": {
                    "config_context": {
                        "credentials": [
                            {"username": "admin", "password": seal_secret("adminpw")},
                            {"username": "noc", "password": seal_secret("nocpw")},
                        ]
                    }
                }
            },
            capabilities={Capability.IDENTITY},
            status=DeviceStatus.OK,
        )
        context = build_jinja_context(device, run_id="run-1", workflow_id="wf-1")
        rendered = render_jinja_template(
            "{% for c in nautobot.config_context.credentials %}"
            "user {{ c.username }} secret {{ c.password }}\n"
            "{% endfor %}",
            context,
        )
        self.assertIn("user admin secret adminpw", rendered)
        self.assertIn("user noc secret nocpw", rendered)


if __name__ == "__main__":
    unittest.main()


class MultilineValueTests(unittest.TestCase):
    """S4-08: a data value with a line break must not become extra device commands."""

    def test_value_with_newline_is_rejected_by_default(self) -> None:
        from workflow_steps.common.jinja_render import UnsafeTemplateValueError

        with self.assertRaises(UnsafeTemplateValueError) as ctx:
            render_jinja_template(
                "interface Gi0/1\n description {{ desc }}\n",
                {"desc": "uplink\nusername backdoor privilege 15 secret 0 Pwned!"},
            )
        failure = ctx.exception.failure
        self.assertEqual(failure.kind, "unsafe_template_value")
        self.assertEqual(failure.line, 2)
        self.assertNotIn("backdoor", str(ctx.exception))

    def test_carriage_return_is_rejected_too(self) -> None:
        from workflow_steps.common.jinja_render import UnsafeTemplateValueError

        with self.assertRaises(UnsafeTemplateValueError):
            render_jinja_template("x {{ v }}", {"v": "a\rb"})

    def test_every_splitlines_separator_is_rejected(self) -> None:
        from workflow_steps.common.jinja_render import UnsafeTemplateValueError

        for char in (
            "\n",
            "\r",
            "\x0b",
            "\x0c",
            "\x1c",
            "\x1d",
            "\x1e",
            "\x85",
            "\u2028",
            "\u2029",
        ):
            with self.subTest(char=repr(char)):
                with self.assertRaises(UnsafeTemplateValueError):
                    render_jinja_template("x {{ v }}", {"v": f"a{char}shutdown"})

    def test_allow_multiline_values_still_accepts_them(self) -> None:
        self.assertEqual(
            render_jinja_template("{{ v }}", {"v": "a\x0bb"}, allow_multiline_values=True), "a\x0bb"
        )

    def test_template_literal_newlines_are_allowed(self) -> None:
        self.assertEqual(
            render_jinja_template("line1\nline2 {{ v }}\nline3", {"v": "ok"}),
            "line1\nline2 ok\nline3",
        )

    def test_opt_out_allows_multiline_values(self) -> None:
        self.assertEqual(
            render_jinja_template("{{ v }}", {"v": "a\nb"}, allow_multiline_values=True), "a\nb"
        )

    def test_join_newline_is_rejected_without_opt_out(self) -> None:
        from workflow_steps.common.jinja_render import UnsafeTemplateValueError

        with self.assertRaises(UnsafeTemplateValueError):
            render_jinja_template("{{ items | join('\\n') }}", {"items": ["a", "b"]})
