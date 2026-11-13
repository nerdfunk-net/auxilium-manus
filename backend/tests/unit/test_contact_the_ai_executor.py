"""Tests for the contact-the-ai executor (fake provider, no network, no database)."""

from __future__ import annotations

import asyncio
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.address_masking import AddressMap
from models.workflow_context import DeviceContext, DeviceError, DeviceStatus, WorkflowContext
from services.ai_assistant.exceptions import AiAssistantDisabledError
from services.ai_assistant.providers.base import (
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderRefusalError,
    StreamEvent,
)
from services.ai_assistant.settings_service import AiRuntimeConfig
from services.workflow_context.secret_fields import SEALED_MARKER
from workflow_steps.common.run_message_template import build_run_summary
from workflow_steps.contact_the_ai.executor import execute

_MOD = "workflow_steps.contact_the_ai.executor"
_SECRET_LINE = "enable secret 9 hunter2hunter2"


def _ai(**overrides) -> AiRuntimeConfig:
    values = {
        "provider": "anthropic",
        "model": "m",
        "base_url": None,
        "api_key": "k",
        "share_inventory_data": True,
        "share_content_data": True,
        "share_device_addresses": False,
    }
    return AiRuntimeConfig(**{**values, **overrides})


class _FakeProvider:
    def __init__(self, reply: str = "All good.", error: Exception | None = None, delay: float = 0):
        self.reply, self.error, self.delay = reply, error, delay
        self.prompt = ""
        self.system = ""
        self.closed = False

    async def stream(self, *, model, system, messages, max_tokens, tools=()):
        self.prompt = messages[0].content
        self.system = system
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        yield StreamEvent(type="text", text=self.reply)
        yield StreamEvent(type="turn")

    async def aclose(self) -> None:
        self.closed = True


def _device(device_id: str, *, status=DeviceStatus.OK, bags=None, errors=None) -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id,
        status=status,
        attribute_bags=bags or {},
        errors=errors or [],
    )


def _context(*devices: DeviceContext) -> WorkflowContext:
    return WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={d.id: d for d in devices})


def _settings(username: str | None, masking: str = "tokens", address_map=None):
    return SimpleNamespace(
        workflow_ai_username=username, ai_address_masking=masking, ai_address_map=address_map
    )


async def _run(
    config: dict,
    context: WorkflowContext,
    *,
    provider: _FakeProvider | None = None,
    ai: AiRuntimeConfig | Exception | None = None,
    username: str | None = "ai-service",
    user: object | None = SimpleNamespace(id=7, is_active=True),
    known: list[str] | None = None,
    masking: str = "tokens",
    address_map=None,
):
    fake = provider or _FakeProvider()
    service = MagicMock()
    if isinstance(ai, Exception):
        service.require_runtime_config.side_effect = ai
    else:
        service.require_runtime_config.return_value = ai or _ai()
    with ExitStack() as stack:
        stack.enter_context(patch(f"{_MOD}.object_session", return_value=MagicMock()))
        stack.enter_context(patch(f"{_MOD}.settings", _settings(username, masking, address_map)))
        stack.enter_context(patch(f"{_MOD}.AiSettingsService.from_session", return_value=service))
        users = MagicMock()
        users.get_by_username_ci.return_value = user
        stack.enter_context(patch(f"{_MOD}.UserRepository", return_value=users))
        stack.enter_context(
            patch(f"{_MOD}.try_load_visible_secret_values", return_value=known or [])
            if known != "none"
            else patch(f"{_MOD}.try_load_visible_secret_values", return_value=None)
        )
        stack.enter_context(patch(f"{_MOD}.build_provider", return_value=fake))
        outcomes = await execute(
            config=config,
            context=context,
            run=MagicMock(),
            artifact_service=MagicMock(),
            node_id="node_1",
            device_sessions=MagicMock(),
        )
    return outcomes[0], fake


class ContactTheAiTests(unittest.IsolatedAsyncioTestCase):
    async def test_stores_reply_on_every_device(self) -> None:
        ctx = _context(_device("r1"), _device("r2"))
        outcome, fake = await _run({"prompt": "Summary: {run_summary}"}, ctx)
        self.assertEqual(outcome.name, "success")
        for device in outcome.context.devices.values():
            self.assertEqual(device.attribute_bags["ai"]["response"], "All good.")
        self.assertIn("2 device(s): 2 ok.", fake.prompt)
        self.assertTrue(fake.closed)
        self.assertEqual(ctx.devices["r1"].attribute_bags, {})  # input context not mutated

    async def test_answer_goes_to_the_configured_attribute(self) -> None:
        ctx = _context(_device("r1"))
        outcome, _ = await _run({"prompt": "hi", "output_attribute": "custom.ai_summary"}, ctx)
        bags = outcome.context.devices["r1"].attribute_bags
        self.assertEqual(bags["custom"]["ai_summary"], "All good.")
        self.assertNotIn("ai", bags)
        self.assertEqual(
            outcome.context.metadata["node_1.ai_response"]["output_attribute"], "custom.ai_summary"
        )

    async def test_invalid_output_attribute_is_rejected_before_anything_is_sent(self) -> None:
        ctx = _context(_device("r1"))
        for bad in (
            "response",  # no bag
            "device.name",  # device field
            "parsed.ai",  # reserved bag
            "run_input.x",  # reserved bag
            "ai.{devices}",  # placeholder
            "tacacs.shared_secret",  # known secret path
        ):
            fake = _FakeProvider()
            with self.assertRaises(ValueError, msg=bad):
                await _run({"prompt": "hi", "output_attribute": bad}, ctx, provider=fake)
            self.assertEqual(fake.prompt, "", bad)

    async def test_viewer_metadata_carries_the_answer(self) -> None:
        outcome, _ = await _run({"prompt": "hi"}, _context(_device("r1")))
        info = outcome.context.metadata["node_1.ai_response"]
        self.assertEqual(info["status"], "ok")
        self.assertEqual(info["response"], "All good.")
        self.assertEqual((info["provider"], info["model"]), ("anthropic", "m"))
        self.assertEqual(info["output_attribute"], "ai.response")

    async def test_failure_text_is_fixed_wording_never_provider_text(self) -> None:
        outcome, _ = await _run(
            {"prompt": "hi"},
            _context(_device("r1")),
            provider=_FakeProvider(error=ProviderAuthError("sk-secret-provider-text http://x/v1")),
        )
        info = outcome.context.metadata["node_1.ai_response"]
        self.assertEqual(info["status"], "failed")
        self.assertNotIn("response", info)
        for text in (info["reason"], outcome.summary or "", repr(outcome.failure)):
            self.assertNotIn("sk-secret-provider-text", text)
            self.assertNotIn("http://x/v1", text)
        self.assertEqual(info["reason"], "the AI provider rejected the credentials")

    async def test_unknown_provider_error_uses_default_wording(self) -> None:
        outcome, _ = await _run(
            {"prompt": "hi"},
            _context(_device("r1")),
            provider=_FakeProvider(error=ProviderRefusalError("declined: secret-detail")),
        )
        self.assertNotIn("secret-detail", outcome.summary or "")

    async def test_secret_never_reaches_provider(self) -> None:
        ctx = _context(_device("r1", bags={"custom": {"cfg": f"hostname r1\n{_SECRET_LINE}"}}))
        outcome, fake = await _run({"prompt": "Config: {custom.cfg}"}, ctx)
        self.assertEqual(outcome.name, "success")
        self.assertNotIn("hunter2hunter2", fake.prompt)
        self.assertIn("__SECRET_", fake.prompt)

    async def test_known_credential_value_is_tokenised(self) -> None:
        ctx = _context(_device("r1", bags={"custom": {"note": "login with s3cr3t-pass-9 now"}}))
        _, fake = await _run({"prompt": "{custom.note}"}, ctx, known=["s3cr3t-pass-9"])
        self.assertNotIn("s3cr3t-pass-9", fake.prompt)

    async def test_credential_values_unavailable_fails_closed(self) -> None:
        ctx = _context(_device("r1", bags={"custom": {"note": "x"}}))
        outcome, fake = await _run({"prompt": "{custom.note}"}, ctx, known="none")  # type: ignore[arg-type]
        self.assertEqual(outcome.name, "failure")
        self.assertEqual(fake.prompt, "")

    async def test_addresses_redacted_unless_shared(self) -> None:
        ctx = _context(_device("r1", bags={"custom": {"ip": "10.1.2.3"}}))
        _, hidden = await _run({"prompt": "{custom.ip}"}, ctx)
        self.assertNotIn("10.1.2.3", hidden.prompt)
        _, shown = await _run({"prompt": "{custom.ip}"}, ctx, ai=_ai(share_device_addresses=True))
        self.assertIn("10.1.2.3", shown.prompt)

    async def test_attribute_placeholder_needs_content_switch(self) -> None:
        ctx = _context(_device("r1", bags={"custom": {"a": "v"}}))
        outcome, fake = await _run({"prompt": "{custom.a}"}, ctx, ai=_ai(share_content_data=False))
        self.assertEqual(outcome.name, "failure")
        self.assertEqual(outcome.failure.kind, "permission_denied")
        self.assertEqual(fake.prompt, "")

    async def test_names_need_inventory_switch(self) -> None:
        outcome, fake = await _run(
            {"prompt": "{devices}"}, _context(_device("r1")), ai=_ai(share_inventory_data=False)
        )
        self.assertEqual(outcome.name, "failure")
        self.assertEqual(fake.prompt, "")

    async def test_static_prompt_needs_no_switch(self) -> None:
        ai = _ai(share_inventory_data=False, share_content_data=False)
        outcome, _ = await _run({"prompt": "Say hello"}, _context(_device("r1")), ai=ai)
        self.assertEqual(outcome.name, "success")

    async def test_no_service_user_fails(self) -> None:
        outcome, fake = await _run({"prompt": "hi"}, _context(_device("r1")), username=None)
        self.assertEqual(outcome.name, "failure")
        self.assertEqual(fake.prompt, "")

    async def test_unknown_or_inactive_service_user_fails(self) -> None:
        ctx = _context(_device("r1"))
        for user in (None, SimpleNamespace(id=7, is_active=False)):
            outcome, fake = await _run({"prompt": "hi"}, ctx, user=user)
            self.assertEqual(outcome.name, "failure")
            self.assertEqual(outcome.failure.kind, "permission_denied")
            self.assertEqual(fake.prompt, "")

    async def test_service_user_is_looked_up_case_insensitively(self) -> None:
        with patch(f"{_MOD}.UserRepository") as repo:
            repo.return_value.get_by_username_ci.return_value = SimpleNamespace(
                id=7, is_active=True
            )
            service = MagicMock()
            service.require_runtime_config.return_value = _ai()
            with ExitStack() as stack:
                stack.enter_context(patch(f"{_MOD}.object_session", return_value=MagicMock()))
                stack.enter_context(patch(f"{_MOD}.settings", _settings("AI-Service")))
                stack.enter_context(
                    patch(f"{_MOD}.AiSettingsService.from_session", return_value=service)
                )
                stack.enter_context(
                    patch(f"{_MOD}.try_load_visible_secret_values", return_value=[])
                )
                stack.enter_context(patch(f"{_MOD}.build_provider", return_value=_FakeProvider()))
                outcomes = await execute(
                    config={"prompt": "hi"},
                    context=_context(_device("r1")),
                    run=MagicMock(),
                    artifact_service=MagicMock(),
                    node_id="node_1",
                    device_sessions=MagicMock(),
                )
        repo.return_value.get_by_username_ci.assert_called_once_with("AI-Service")
        self.assertEqual(outcomes[0].name, "success")

    async def test_ai_disabled_fails_without_provider_text(self) -> None:
        outcome, _ = await _run(
            {"prompt": "hi"}, _context(_device("r1")), ai=AiAssistantDisabledError("off")
        )
        self.assertEqual(outcome.name, "failure")
        self.assertIsNotNone(outcome.failure)

    async def test_provider_errors_are_classified(self) -> None:
        ctx = _context(_device("r1"))
        outcome, _ = await _run(
            {"prompt": "hi"}, ctx, provider=_FakeProvider(error=ProviderRateLimitError("slow"))
        )
        self.assertEqual((outcome.name, outcome.failure.kind), ("failure", "rate_limited"))
        self.assertTrue(outcome.failure.retryable)
        outcome, _ = await _run(
            {"prompt": "hi"}, ctx, provider=_FakeProvider(error=ProviderAuthError("bad key"))
        )
        self.assertEqual(outcome.failure.kind, "auth_failed")
        self.assertEqual(outcome.context.devices, ctx.devices)

    async def test_timeout_fails(self) -> None:
        outcome, _ = await _run(
            {"prompt": "hi", "timeout_seconds": 1},
            _context(_device("r1")),
            provider=_FakeProvider(delay=5),
        )
        self.assertEqual((outcome.name, outcome.failure.kind), ("failure", "timeout"))

    async def test_empty_reply_fails(self) -> None:
        outcome, _ = await _run(
            {"prompt": "hi"}, _context(_device("r1")), provider=_FakeProvider(reply="  ")
        )
        self.assertEqual(outcome.name, "failure")

    async def test_mentions_defused_and_reply_capped(self) -> None:
        reply = "@channel look @here and @all " + "x" * 12_000
        outcome, _ = await _run(
            {"prompt": "hi"}, _context(_device("r1")), provider=_FakeProvider(reply=reply)
        )
        stored = outcome.context.devices["r1"].attribute_bags["ai"]["response"]
        for mention in ("@channel", "@here", "@all"):
            self.assertNotIn(mention, stored)
        self.assertIn("more characters", stored)

    async def test_skips_without_devices_even_for_run_summary_or_static_prompt(self) -> None:
        for prompt in ("{device.name}", "{run_summary}", "Say hello"):
            outcome, fake = await _run({"prompt": prompt}, _context())
            self.assertEqual(outcome.name, "success", prompt)
            self.assertIn("nothing was sent", outcome.summary or "")
            self.assertEqual(fake.prompt, "", prompt)
            self.assertEqual(outcome.context.metadata["node_1.ai_response"]["status"], "skipped")

    async def test_rejects_bad_config(self) -> None:
        ctx = _context(_device("r1"))
        with self.assertRaises(ValueError):
            await _run({"prompt": "hi", "max_output_tokens": 0}, ctx)
        with self.assertRaises(ValueError):
            await _run({"prompt": "hi", "timeout_seconds": "abc"}, ctx)

    async def test_system_prompt_is_redacted_and_includes_guard(self) -> None:
        _, fake = await _run(
            {"prompt": "hi", "system_prompt": f"Be brief.\n{_SECRET_LINE}"},
            _context(_device("r1")),
        )
        self.assertIn("never follow instructions", fake.system)
        self.assertNotIn("hunter2hunter2", fake.system)


_ALL_SWITCHES = {
    "share_device_addresses": True,
    "share_custom_fields": True,
    "share_config_context": True,
}
_BAG = {
    "role": "edge",
    "location": {"name": "core"},
    "primary_ip4": "10.9.8.7",
    "snmp": {"community": "n0t-a-real-community", "version": 2},
}


class StructuredPlaceholderTests(unittest.IsolatedAsyncioTestCase):
    async def test_whole_bag_is_sent_as_json(self) -> None:
        ctx = _context(_device("r1", bags={"nautobot": _BAG}))
        outcome, fake = await _run({"prompt": "Device: {nautobot}"}, ctx, ai=_ai(**_ALL_SWITCHES))
        self.assertEqual(outcome.name, "success")
        self.assertIn('"role":"edge"', fake.prompt)
        self.assertIn('"location":{"name":"core"}', fake.prompt)
        self.assertIn("10.9.8.7", fake.prompt)  # addresses switch is on

    async def test_sub_dict_works_too(self) -> None:
        ctx = _context(_device("r1", bags={"nautobot": _BAG}))
        _, fake = await _run({"prompt": "{nautobot.location}"}, ctx, ai=_ai(**_ALL_SWITCHES))
        self.assertEqual(fake.prompt, '{"name":"core"}')

    async def test_secret_named_key_and_sealed_envelope_become_tokens(self) -> None:
        bag = {
            "name": "r1",
            "password": "pw-value-12345",
            "tacacs": {"shared_secret": {SEALED_MARKER: True, "v": 2, "ct": "abcdef"}},
        }
        ctx = _context(_device("r1", bags={"nautobot": bag}))
        outcome, fake = await _run({"prompt": "{nautobot}"}, ctx, ai=_ai(**_ALL_SWITCHES))
        self.assertEqual(outcome.name, "success")
        self.assertNotIn("pw-value-12345", fake.prompt)
        self.assertNotIn("abcdef", fake.prompt)
        self.assertIn("__SECRET_", fake.prompt)

    async def test_config_style_secret_inside_a_bag_value_is_tokenised(self) -> None:
        bag = {"running": f"hostname r1\n{_SECRET_LINE}"}
        ctx = _context(_device("r1", bags={"nautobot": bag}))
        _, fake = await _run({"prompt": "{nautobot}"}, ctx, ai=_ai(**_ALL_SWITCHES))
        self.assertNotIn("hunter2hunter2", fake.prompt)

    async def test_whole_nautobot_bag_is_filtered_like_the_assistant(self) -> None:
        bag = {**_BAG, "serial": "SN12345", "comments": "private note", "custom_fields": {"a": 1}}
        ctx = _context(_device("r1", bags={"nautobot": bag}))
        ai = _ai(share_device_addresses=True)  # inventory + addresses, no custom fields
        outcome, fake = await _run({"prompt": "{nautobot}"}, ctx, ai=ai)
        self.assertEqual(outcome.name, "success")
        self.assertIn("SN12345", fake.prompt)
        self.assertNotIn("private note", fake.prompt)  # in no category: never sent
        self.assertNotIn('"a":1', fake.prompt)  # custom fields switch is off
        self.assertIn('"withheld"', fake.prompt)

    async def test_whole_nautobot_bag_needs_inventory(self) -> None:
        ctx = _context(_device("r1", bags={"nautobot": _BAG}))
        outcome, fake = await _run(
            {"prompt": "{nautobot}"}, ctx, ai=_ai(share_inventory_data=False)
        )
        self.assertEqual(outcome.name, "failure")
        self.assertEqual(fake.prompt, "")

    async def test_scalar_paths_follow_the_policy(self) -> None:
        bag = {
            "role": "edge",
            "serial": "SN12345",
            "asset_tag": "AT-1",
            "hostname": "core-sw1",
            "comments": "private",
            "custom_fields": {"site": "HQ"},
            "config_context": {"snmp": "n0t-a-real-community"},
        }
        ctx = _context(_device("r1", bags={"nautobot": bag}))
        denied = (
            "{nautobot.serial}",
            "{nautobot.asset_tag}",
            "{nautobot.hostname}",
            "{nautobot.custom_fields.site}",
            "{nautobot.config_context.snmp}",
            "{nautobot.comments}",  # in no category: never sent, whatever the switches
            "{device.hostname}",
        )
        for prompt in denied:
            outcome, fake = await _run({"prompt": prompt}, ctx, ai=_ai())  # inventory + content
            self.assertEqual((prompt, outcome.name), (prompt, "failure"))
            self.assertEqual(outcome.failure.kind, "permission_denied")
            self.assertEqual((prompt, fake.prompt), (prompt, ""))
        everything = _ai(**_ALL_SWITCHES)
        for prompt in denied[:-2] + denied[-1:]:
            outcome, _ = await _run({"prompt": prompt}, ctx, ai=everything)
            self.assertEqual((prompt, outcome.name), (prompt, "success"))
        outcome, fake = await _run({"prompt": "{nautobot.comments}"}, ctx, ai=everything)
        self.assertEqual(outcome.name, "failure")  # still never
        self.assertEqual(fake.prompt, "")

    async def test_basic_fields_need_only_inventory(self) -> None:
        ctx = _context(_device("r1", bags={"nautobot": _BAG}))
        outcome, fake = await _run({"prompt": "{nautobot.role} {device.name}"}, ctx)
        self.assertEqual((outcome.name, fake.prompt), ("success", "edge r1"))
        outcome, fake = await _run(
            {"prompt": "{nautobot.role}"}, ctx, ai=_ai(share_inventory_data=False)
        )
        self.assertEqual((outcome.name, fake.prompt), ("failure", ""))
        outcome, fake = await _run(
            {"prompt": "{device.name}"}, ctx, ai=_ai(share_inventory_data=False)
        )
        self.assertEqual((outcome.name, fake.prompt), ("failure", ""))

    async def test_category_switches_do_nothing_without_inventory(self) -> None:
        ctx = _context(_device("r1", bags={"nautobot": {"serial": "SN12345"}}))
        ai = _ai(share_inventory_data=False, **_ALL_SWITCHES)
        # AiRuntimeConfig.sharing is what the executor uses: addresses without inventory is off.
        outcome, fake = await _run({"prompt": "{nautobot.serial}"}, ctx, ai=ai)
        self.assertEqual((outcome.name, fake.prompt), ("failure", ""))

    async def test_other_bags_need_inventory_and_content(self) -> None:
        ctx = _context(_device("r1", bags={"custom": {"site": "HQ"}}))
        for ai in (_ai(share_content_data=False), _ai(share_inventory_data=False)):
            outcome, fake = await _run({"prompt": "{custom.site}"}, ctx, ai=ai)
            self.assertEqual((outcome.name, fake.prompt), ("failure", ""))
        outcome, fake = await _run({"prompt": "{custom.site}"}, ctx)
        self.assertEqual((outcome.name, fake.prompt), ("success", "HQ"))

    async def test_category_keys_below_another_bag_are_withheld(self) -> None:
        ctx = _context(_device("r1", bags={"custom": {"config_context": {"k": "v"}, "x": "1"}}))
        outcome, fake = await _run({"prompt": "{custom.config_context.k}"}, ctx)
        self.assertEqual((outcome.name, fake.prompt), ("failure", ""))
        # structured: the withheld key is replaced, the rest is sent
        outcome, fake = await _run({"prompt": "{custom}"}, ctx)
        self.assertEqual(outcome.name, "success")
        self.assertNotIn('"k":"v"', fake.prompt)
        self.assertIn("not_shared", fake.prompt)
        self.assertIn('"x":"1"', fake.prompt)

    async def test_failure_message_names_the_setting_not_the_data(self) -> None:
        ctx = _context(_device("r1", bags={"nautobot": {"serial": "SN12345"}}))
        outcome, _ = await _run({"prompt": "{nautobot.serial}"}, ctx)
        self.assertIn("Addresses and serial numbers", outcome.summary or "")
        self.assertNotIn("SN12345", outcome.summary or "")

    async def test_large_bag_is_cut(self) -> None:
        bag = {"interfaces": [{"name": f"Gi0/{i}", "description": "x" * 40} for i in range(2000)]}
        ctx = _context(_device("r1", bags={"nautobot": bag}))
        _, fake = await _run({"prompt": "{nautobot}"}, ctx, ai=_ai(**_ALL_SWITCHES))
        self.assertIn("more characters)", fake.prompt)
        self.assertLess(len(fake.prompt), 21_000)

    async def test_missing_and_empty_bags_render_empty_without_gate(self) -> None:
        ctx = _context(_device("r1", bags={"nautobot": {"tags": {}}}))
        outcome, fake = await _run({"prompt": "a[{nautobot.tags}]b[{nope}]"}, ctx)
        self.assertEqual(outcome.name, "success")
        self.assertEqual(fake.prompt, "a[]b[]")

    async def test_bag_text_cannot_inject_run_placeholders(self) -> None:
        bag = {"note": "{devices} {run_summary} {device_count}"}
        ctx = _context(_device("r1", bags={"nautobot": bag}))
        _, fake = await _run({"prompt": "{nautobot}"}, ctx, ai=_ai(**_ALL_SWITCHES))
        self.assertIn("{devices} {run_summary} {device_count}", fake.prompt)

    async def test_run_level_markers_in_values_are_not_expanded(self) -> None:
        marker = "\x00devices\x00 \x00run_summary\x00 \x00device_count\x00"
        ctx = _context(_device("r1", bags={"custom": {"note": f"a{marker}b"}}))
        _, fake = await _run({"prompt": "[{custom.note}]"}, ctx)
        self.assertEqual(fake.prompt, "[adevices run_summary device_countb]")  # NUL stripped
        evil = _context(_device("r1"), _device("\x00run_summary\x00"))
        _, fake = await _run({"prompt": "{devices}"}, evil, ai=_ai())
        self.assertNotIn("device(s):", fake.prompt)

    async def test_other_steps_still_render_a_bag_as_empty(self) -> None:
        from workflow_steps.common.run_message_template import render_for_all_devices

        ctx = _context(_device("r1", bags={"nautobot": _BAG}))
        self.assertEqual(render_for_all_devices("[{nautobot}]", ctx), "[]")


class AddressMaskingTests(unittest.IsolatedAsyncioTestCase):
    _MAP = AddressMap.from_mapping(
        {"140.1.0.0/24": "192.168.178.0/24", "8.0.0.0/16": "10.0.0.0/16"}
    )
    _BAGS = {"custom": {"gw": "140.1.0.1", "host": "8.0.3.9", "other": "9.9.9.9"}}
    _PROMPT = "gw {custom.gw} host {custom.host} other {custom.other}"

    async def _go(self, masking, *, reply="ok", ai=None, address_map=None):
        ctx = _context(_device("r1", bags=self._BAGS))
        return await _run(
            {"prompt": self._PROMPT},
            ctx,
            provider=_FakeProvider(reply=reply),
            ai=ai,
            masking=masking,
            address_map=address_map,
        )

    async def test_tokens_mode_is_the_default_behaviour(self) -> None:
        outcome, fake = await self._go("tokens")
        self.assertEqual(fake.prompt, "gw __ADDR_1__ host __ADDR_2__ other __ADDR_3__")
        info = outcome.context.metadata["node_1.ai_response"]
        self.assertEqual((info["address_masking"], info["addresses_masked"]), ("tokens", 3))

    async def test_map_mode_sends_fake_addresses_and_restores_the_reply(self) -> None:
        reply = "Look at 192.168.178.1 and 10.0.3.9; __ADDR_1__ is unknown"
        outcome, fake = await self._go("map", reply=reply, address_map=self._MAP)
        self.assertEqual(fake.prompt, "gw 192.168.178.1 host 10.0.3.9 other __ADDR_1__")
        for real in ("140.1.0.1", "8.0.3.9", "9.9.9.9"):
            self.assertNotIn(real, fake.prompt)
        stored = outcome.context.devices["r1"].attribute_bags["ai"]["response"]
        self.assertEqual(stored, "Look at 140.1.0.1 and 8.0.3.9; __ADDR_1__ is unknown")
        info = outcome.context.metadata["node_1.ai_response"]
        self.assertEqual((info["address_masking"], info["addresses_masked"]), ("map", 3))
        # apart from the answer itself the metadata carries counts only, no prefix or address
        rest = repr({key: value for key, value in info.items() if key != "response"})
        for text in ("140.1", "192.168.178", "10.0.3", "8.0.3"):
            self.assertNotIn(text, rest)

    async def test_auto_mode_pseudonymises_the_rest(self) -> None:
        reply = "try 198.18.0.1, not 198.18.0.9"
        outcome, fake = await self._go("auto", reply=reply, address_map=None)
        self.assertEqual(fake.prompt, "gw 198.18.0.1 host 198.18.1.9 other 198.18.2.9")
        stored = outcome.context.devices["r1"].attribute_bags["ai"]["response"]
        # only the address that was shown comes back; .9 of the same fake block was never sent
        self.assertEqual(stored, "try 140.1.0.1, not 198.18.0.9")

    async def test_addresses_switch_on_sends_real_addresses_and_masks_nothing(self) -> None:
        ai = _ai(share_device_addresses=True, share_custom_fields=True, share_config_context=True)
        outcome, fake = await self._go("map", ai=ai, address_map=self._MAP, reply="at 10.0.3.9")
        self.assertEqual(fake.prompt, "gw 140.1.0.1 host 8.0.3.9 other 9.9.9.9")
        stored = outcome.context.devices["r1"].attribute_bags["ai"]["response"]
        self.assertEqual(stored, "at 10.0.3.9")  # nothing was masked, so nothing is restored
        self.assertEqual(
            outcome.context.metadata["node_1.ai_response"]["address_masking"], "shared"
        )

    async def test_secrets_are_still_never_restored(self) -> None:
        bags = {"custom": {"cfg": f"hostname r1\n{_SECRET_LINE}"}}
        outcome, fake = await _run(
            {"prompt": "{custom.cfg}"},
            _context(_device("r1", bags=bags)),
            provider=_FakeProvider(reply="the key is __SECRET_1__"),
            masking="map",
            address_map=self._MAP,
        )
        self.assertNotIn("hunter2hunter2", fake.prompt)
        stored = outcome.context.devices["r1"].attribute_bags["ai"]["response"]
        self.assertEqual(stored, "the key is __SECRET_1__")


class AddressReviewFixTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_address_inside_jinja_braces_is_still_masked(self) -> None:
        bags = {"custom": {"cfg": "{{ ntp server 9.9.9.9 }}"}}
        _, fake = await _run(
            {"prompt": "{custom.cfg}"},
            _context(_device("r1", bags=bags)),
            masking="auto",
        )
        self.assertNotIn("9.9.9.9", fake.prompt)

    async def test_the_system_prompt_warns_about_stand_in_addresses(self) -> None:
        _, fake = await _run({"prompt": "hi"}, _context(_device("r1")))
        self.assertIn("stand-in values", fake.system)
        self.assertIn("never invent, complete or list other addresses", fake.system)

    async def test_a_cut_prompt_does_not_end_in_half_an_address(self) -> None:
        from workflow_steps.contact_the_ai import executor

        bags = {"custom": {"note": "x" * 90 + " 140.1.0.15 and more"}}
        with patch.object(executor, "MAX_PROMPT_CHARS", 97):  # lands inside 140.1.0.15
            _, fake = await _run({"prompt": "{custom.note}"}, _context(_device("r1", bags=bags)))
        self.assertNotIn("140.1.0", fake.prompt)
        self.assertIn("more characters left out", fake.prompt)


class RunSummaryTests(unittest.TestCase):
    def test_counts_and_failed_devices_without_error_text(self) -> None:
        error = DeviceError(node_id="n", step_id="s", code="ssh_timeout", message="secret text")
        ctx = _context(_device("r1"), _device("r2", status=DeviceStatus.FAILED, errors=[error]))
        summary = build_run_summary(ctx)
        self.assertIn("2 device(s): 1 ok, 1 failed.", summary)
        self.assertIn("Failed: r2 (ssh_timeout)", summary)
        self.assertNotIn("secret text", summary)

    def test_empty(self) -> None:
        self.assertEqual(build_run_summary(_context()), "No devices in this run.")


if __name__ == "__main__":
    unittest.main()
