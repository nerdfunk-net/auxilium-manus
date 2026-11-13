"""Reversible address masking (core/address_masking.py) and its use by the Redactor."""

from __future__ import annotations

import ipaddress
import re
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from core.address_masking import (
    AUTO_POOL_V4,
    AddressMap,
    AddressMapError,
    AddressMasker,
    build_masker,
    is_meaning_only,
    load_address_map,
    resolve_map_path,
    validate_masking_config,
)
from services.ai_assistant.redaction import Redactor

_EXAMPLE = {"140.1.0.0/24": "192.168.178.0/24", "8.0.0.0/16": "10.0.0.0/16"}


def _map(raw: dict | None = None) -> AddressMap:
    return AddressMap.from_mapping(raw or _EXAMPLE)


def _redactor(mode: str = "map", raw: dict | None = None) -> Redactor:
    return Redactor(address_masker=build_masker(mode, _map(raw) if mode != "auto" else None))


class AddressMapValidationTests(unittest.TestCase):
    def test_example_from_the_issue_is_valid(self) -> None:
        self.assertEqual(len(_map()), 2)

    def test_rejects_bad_entries(self) -> None:
        bad = {
            "not a prefix": {"nope": "10.0.0.0/24"},
            "host bits set": {"10.0.0.1/24": "192.168.0.0/24"},
            "different length": {"10.0.0.0/24": "192.168.0.0/16"},
            "different family": {"10.0.0.0/24": "2001:db8::/24"},
            "value not text": {"10.0.0.0/24": 5},
            "source overlap": {"10.0.0.0/16": "1.0.0.0/16", "10.0.1.0/16": "2.0.0.0/16"},
            "target overlap": {"10.0.0.0/24": "1.0.0.0/24", "11.0.0.0/24": "1.0.0.0/24"},
            "nested sources": {"10.0.0.0/8": "1.0.0.0/8", "10.1.0.0/16": "2.1.0.0/16"},
            "target in source": {"10.0.0.0/24": "10.0.0.0/24"},
            "target hits another source": {
                "10.0.0.0/24": "20.0.0.0/24",
                "20.0.0.0/24": "30.0.0.0/24",
            },
        }
        for name, raw in bad.items():
            with self.subTest(name), self.assertRaises(AddressMapError):
                AddressMap.from_mapping(raw)

    def test_ipv6_entry(self) -> None:
        mapping = _map({"2a00:1::/64": "2001:db8:5::/64"})
        fake = mapping.to_fake(ipaddress.ip_address("2a00:1::42"))
        self.assertEqual(str(fake), "2001:db8:5::42")
        self.assertEqual(str(mapping.to_real(fake)), "2a00:1::42")  # type: ignore[arg-type]

    def test_file_loading_errors_name_the_file(self) -> None:
        with TemporaryDirectory() as tmp:
            for name, text in {
                "empty.yaml": "",
                "list.yaml": "- 1\n- 2\n",
                "yaml.yaml": "a: [unclosed\n",
                "bad.yaml": "10.0.0.0/24: nonsense\n",
            }.items():
                path = Path(tmp) / name
                path.write_text(text)
                with self.subTest(name), self.assertRaises(AddressMapError) as ctx:
                    load_address_map(path)
                self.assertIn(name, str(ctx.exception))
            with self.assertRaises(AddressMapError):
                load_address_map(Path(tmp) / "missing.yaml")

    def test_file_loading_ok_and_size_cap(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "map.yaml"
            path.write_text(
                textwrap.dedent("""\
                ---
                140.1.0.0/24: 192.168.178.0/24
                8.0.0.0/16: 10.0.0.0/16
                """)
            )
            self.assertEqual(len(load_address_map(path)), 2)
            path.write_text("#" * (300 * 1024))
            with self.assertRaises(AddressMapError):
                load_address_map(path)

    def test_mode_rules(self) -> None:
        validate_masking_config("tokens", None)
        validate_masking_config("map", _map())
        validate_masking_config("auto", None)
        validate_masking_config("auto", _map())
        with self.assertRaises(AddressMapError):
            validate_masking_config("map", None)
        with self.assertRaises(AddressMapError):
            validate_masking_config("tokens", _map())
        with self.assertRaises(AddressMapError):
            validate_masking_config("wrong", None)
        with self.assertRaises(AddressMapError):  # a prefix inside the automatic pool
            validate_masking_config("auto", _map({"10.0.0.0/24": "198.18.4.0/24"}))


class MappingMathTests(unittest.TestCase):
    def test_host_position_is_kept_both_ways(self) -> None:
        mapping = _map()
        for real, fake in (
            ("140.1.0.5", "192.168.178.5"),
            ("140.1.0.0", "192.168.178.0"),
            ("140.1.0.255", "192.168.178.255"),
            ("8.0.255.254", "10.0.255.254"),
        ):
            with self.subTest(real):
                self.assertEqual(str(mapping.to_fake(ipaddress.ip_address(real))), fake)
                self.assertEqual(str(mapping.to_real(ipaddress.ip_address(fake))), real)

    def test_outside_every_prefix_is_not_mapped(self) -> None:
        mapping = _map()
        for text in ("140.1.1.5", "9.9.9.9", "192.168.179.1", "8.1.0.1", "0.0.0.1"):
            self.assertIsNone(mapping.to_fake(ipaddress.ip_address(text)), text)

    def test_meaning_only_values(self) -> None:
        for text in ("255.255.255.0", "255.255.255.255", "255.0.0.0", "0.0.0.255", "0.0.0.0"):
            self.assertTrue(is_meaning_only(ipaddress.ip_address(text)), text)
        for text in ("10.0.0.0", "192.0.0.0", "128.0.0.0", "255.0.255.0", "0.1.0.0", "1.2.3.4"):
            self.assertFalse(is_meaning_only(ipaddress.ip_address(text)), text)
        self.assertFalse(is_meaning_only(ipaddress.ip_address("::")))


class MaskerTests(unittest.TestCase):
    def test_map_mode_never_invents_an_unmapped_address(self) -> None:
        masker = AddressMasker(_map(), auto=False)
        self.assertEqual(masker.mask("140.1.0.9"), "192.168.178.9")
        self.assertIsNone(masker.mask("9.9.9.9"))  # the caller tokenises
        self.assertEqual(masker.mask("255.255.255.0"), "255.255.255.0")
        self.assertIsNone(masker.mask("010.001.002.003"))  # odd form: not an address for Python
        self.assertEqual(masker.masked_count, 1)

    def test_auto_groups_by_block_and_keeps_host_bits(self) -> None:
        masker = AddressMasker(None, auto=True)
        a, b, c = masker.mask("9.9.9.5"), masker.mask("9.9.9.200"), masker.mask("9.9.8.5")
        self.assertEqual((a, b), ("198.18.0.5", "198.18.0.200"))  # same /24, same fake /24
        self.assertEqual(c, "198.18.1.5")  # another /24, another fake block
        self.assertEqual(masker.mask("9.9.9.5"), a)  # stable
        self.assertTrue(ipaddress.ip_address(a) in AUTO_POOL_V4)  # type: ignore[arg-type]

    def test_auto_ipv6_and_pool_exhaustion(self) -> None:
        masker = AddressMasker(None, auto=True)
        self.assertEqual(masker.mask("2a00:1:2:3::9"), "2001:db8::9")
        masker = AddressMasker(None, auto=True)
        results = [masker.mask(f"{(i >> 8) % 256 + 1}.{i % 256}.1.1") for i in range(513)]
        self.assertTrue(all(r is not None for r in results[:512]))
        self.assertIsNone(results[512])  # pool used up: the caller tokenises

    def test_auto_prefers_the_file(self) -> None:
        masker = AddressMasker(_map(), auto=True)
        self.assertEqual(masker.mask("140.1.0.7"), "192.168.178.7")
        self.assertEqual(masker.mask("9.9.9.9"), "198.18.0.9")

    def test_each_request_has_its_own_table(self) -> None:
        first, second = AddressMasker(None, auto=True), AddressMasker(None, auto=True)
        first.mask("1.1.1.1")
        self.assertEqual(second.mask("2.2.2.2"), "198.18.0.2")  # not 198.18.1.2

    def test_tokens_mode_has_no_masker(self) -> None:
        self.assertIsNone(build_masker("tokens", None))

    def test_restore_only_touches_what_it_handed_out(self) -> None:
        masker = AddressMasker(None, auto=True)
        masker.mask("9.9.9.5")
        v4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}")
        text = "198.18.0.5 198.18.0.77 198.18.9.1 7.7.7.7 __ADDR_1__ __SECRET_1__"
        restored = masker.restore(text, [v4])
        # exactly the address that was handed out; its neighbours, other fake blocks, real
        # addresses and tokens stay as they are
        self.assertEqual(restored, "9.9.9.5 198.18.0.77 198.18.9.1 7.7.7.7 __ADDR_1__ __SECRET_1__")


class RedactorAddressTests(unittest.TestCase):
    def test_tokens_mode_is_unchanged(self) -> None:
        plain, same = Redactor(), Redactor(address_masker=None)
        text = "r1 10.1.2.3/24 via 10.1.2.1 aa:bb:cc:dd:ee:ff 2001:db8::1 at 12:30:45"
        self.assertEqual(plain.redact_addresses(text), same.redact_addresses(text))
        self.assertEqual(
            plain.redact_addresses(text),
            "r1 __ADDR_1__/24 via __ADDR_2__ __ADDR_3__ __ADDR_4__ at 12:30:45",
        )

    def test_map_replaces_mapped_and_tokenises_the_rest(self) -> None:
        redactor = _redactor()
        out = redactor.redact_addresses(
            "gw 140.1.0.1/24, host 8.0.3.9, other 9.9.9.9, "
            "mask 255.255.255.0, mac aa:bb:cc:dd:ee:ff"
        )
        self.assertEqual(
            out,
            "gw 192.168.178.1/24, host 10.0.3.9, other __ADDR_1__, "
            "mask 255.255.255.0, mac __ADDR_2__",
        )
        self.assertNotIn("140.1.0.1", out)
        self.assertEqual(redactor.masked_address_count, 4)

    def test_fake_addresses_are_not_masked_again(self) -> None:
        # the fake 10.0.3.9 is an ordinary address: a second pass must not tokenise it in one call
        out = _redactor().redact_addresses("a 8.0.3.9 b 8.0.3.9")
        self.assertEqual(out, "a 10.0.3.9 b 10.0.3.9")
        self.assertNotIn("__ADDR_", out)

    def test_fake_ipv6_is_protected_from_the_ipv6_pass(self) -> None:
        redactor = Redactor(address_masker=build_masker("auto", None))
        out = redactor.redact_addresses("peer 2a00:1:2:3::9 and 9.9.9.9")
        self.assertEqual(out, "peer 2001:db8::9 and 198.18.0.9")

    def test_a_fake_ipv4_inside_an_ipv6_form_stays_whole(self) -> None:
        # the IPv6 pass runs after the IPv4 pass and would eat the start of an unprotected fake
        for text in ("::ffff:8.0.3.9", "peer 8.0.3.9::5", "fe80::1 and 8.0.3.9:179"):
            with self.subTest(text):
                out = _redactor().redact_addresses(text)
                self.assertIn("10.0.3.9", out)
                self.assertNotIn("8.0.3.9", out)

    def test_jinja_spans_are_still_left_alone(self) -> None:
        out = _redactor().redact_addresses("{{ 140.1.0.1 }} and 140.1.0.2")
        self.assertEqual(out, "{{ 140.1.0.1 }} and 192.168.178.2")

    def test_round_trip_through_a_reply(self) -> None:
        redactor = _redactor()
        redactor.redact_addresses("gw 140.1.0.1 host 8.0.3.9")
        reply = (
            "Check 192.168.178.1 and 10.0.3.9 first; 10.0.9.9 is in the same range, __ADDR_1__ too"
        )
        self.assertEqual(
            redactor.restore_addresses(reply),
            # a neighbour the model was never shown is not filled in with a real address
            "Check 140.1.0.1 and 8.0.3.9 first; 10.0.9.9 is in the same range, __ADDR_1__ too",
        )

    def test_unknown_addresses_in_a_reply_stay(self) -> None:
        redactor = _redactor()
        self.assertEqual(
            redactor.restore_addresses("see 4.4.4.4 at 12:30:45"), "see 4.4.4.4 at 12:30:45"
        )

    def test_restore_without_masker_is_identity(self) -> None:
        self.assertEqual(Redactor().restore_addresses("192.168.178.1"), "192.168.178.1")


def _auto() -> Redactor:
    return Redactor(address_masker=build_masker("auto", None))


class ReviewRegressionTests(unittest.TestCase):
    """One group per finding of doc/analysis/REVIEW.md (address masking)."""

    # -- 1: restore only puts back what the model was shown ----------------------------------

    def test_restore_does_not_fill_in_a_block_or_change_a_prefix_length(self) -> None:
        redactor = _auto()
        self.assertEqual(redactor.redact_addresses("host 10.1.1.5"), "host 198.18.0.5")
        reply = "gateway 198.18.0.1, pool 198.18.0.0/15, host 198.18.0.5/24"
        self.assertEqual(
            redactor.restore_addresses(reply),
            "gateway 198.18.0.1, pool 198.18.0.0/15, host 10.1.1.5/24",
        )

    def test_restore_ipv6_only_the_shown_address(self) -> None:
        redactor = _auto()
        self.assertEqual(redactor.redact_addresses("peer 2a00:aaaa:bbbb::5"), "peer 2001:db8::5")
        self.assertEqual(
            redactor.restore_addresses("2001:db8::5 and the documentation address 2001:db8::1"),
            "2a00:aaaa:bbbb::5 and the documentation address 2001:db8::1",
        )

    def test_map_restore_is_exact_not_a_whole_prefix(self) -> None:
        redactor = _redactor()
        redactor.redact_addresses("host 8.0.3.9")
        self.assertEqual(
            redactor.restore_addresses("10.0.3.9 10.0.3.10 10.0.0.0/16"),
            "8.0.3.9 10.0.3.10 10.0.0.0/16",
        )

    # -- 2: IPv6 with an embedded IPv4 is one address, prefix included ------------------------

    def test_mixed_ipv6_is_hidden_whole_in_every_mode(self) -> None:
        for text in (
            "2001:db8:1:2:3:4:192.0.2.1",
            "2001:db8:aaaa:bbbb::192.0.2.1",
            "::ffff:192.0.2.1",
            "fe80::192.0.2.1",
        ):
            with self.subTest(text):
                tokens = Redactor().redact_addresses(f"host {text} up")
                self.assertEqual(tokens, "host __ADDR_1__ up")  # one token, no real half
                auto = _auto().redact_addresses(f"host {text} up")
                for real in ("192.0.2.1", "2001:db8:1", "2001:db8:aaaa", "fe80"):
                    self.assertNotIn(real, auto)

    def test_mixed_ipv6_in_the_map_is_replaced_and_restored(self) -> None:
        redactor = _redactor("map", {"2001:db8:1:2:3:4::/96": "fd00:250::/96"})
        out = redactor.redact_addresses("host 2001:db8:1:2:3:4:192.0.2.1")
        self.assertNotIn("2001:db8:1", out)
        self.assertNotIn("192.0.2.1", out)
        fake = out.removeprefix("host ")
        self.assertEqual(redactor.restore_addresses(f"see {fake}"), "see 2001:db8:1:2:3:4:c000:201")

    def test_ipv4_mapped_ipv6_follows_the_ipv4_rules_and_round_trips(self) -> None:
        redactor = _redactor()
        out = redactor.redact_addresses("host ::ffff:8.0.3.9 and ::ffff:9.9.9.9")
        self.assertEqual(out, "host ::ffff:10.0.3.9 and __ADDR_1__")
        self.assertEqual(redactor.restore_addresses("see ::ffff:10.0.3.9"), "see ::ffff:8.0.3.9")

    def test_an_odd_mixed_form_is_tokenised_whole(self) -> None:
        # more than eight groups' worth: not an address Python accepts, still not left half-hidden
        out = _redactor().redact_addresses("x 1:2:3:4:5:6:7:8:9:10.0.0.1 y")
        self.assertNotIn("10.0.0.1", out)

    # -- 3: a pseudonym is never a real address of the request ---------------------------------

    def test_a_pool_address_in_the_text_is_not_passed_through(self) -> None:
        for real in ("198.18.0.5", "2001:db8::1"):
            with self.subTest(real):
                redactor = _auto()
                out = redactor.redact_addresses(f"only {real}")
                self.assertNotIn(real, out)
                self.assertEqual(redactor.masked_address_count, 1)
                self.assertEqual(redactor.restore_addresses(out), f"only {real}")

    def test_a_real_pool_address_is_not_reused_as_a_stand_in(self) -> None:
        for text, reals in (
            ("a 10.1.1.5 b 198.18.0.5", ("10.1.1.5", "198.18.0.5")),
            ("b 198.18.0.5 a 10.1.1.5", ("10.1.1.5", "198.18.0.5")),
        ):
            with self.subTest(text):
                redactor = _auto()
                out = redactor.redact_addresses(text)
                shown = re.findall(r"198\.18\.\d+\.\d+", out)
                self.assertEqual(len(shown), 2)
                self.assertTrue(set(shown).isdisjoint(reals), out)  # no stand-in is a real address
                self.assertEqual(redactor.restore_addresses(out), text)

    def test_a_real_address_equal_to_an_earlier_fake_is_tokenised(self) -> None:
        redactor = _redactor()
        out = redactor.redact_addresses("a 8.0.3.9 b 10.0.3.9")  # 10.0.3.9 is the fake of 8.0.3.9
        self.assertEqual(out, "a 10.0.3.9 b __ADDR_1__")

    def test_a_stand_in_is_never_equal_to_the_address_it_replaces(self) -> None:
        # without observe() the first auto block is 198.18.0.0/24: the guard sends it to a token
        masker = AddressMasker(None, auto=True)
        self.assertIsNone(masker.mask("198.18.0.5"))
        self.assertEqual(masker.masked_count, 0)

    def test_a_real_address_equal_to_a_stand_in_of_an_earlier_text_is_tokenised(self) -> None:
        redactor = _auto()
        self.assertEqual(redactor.redact_addresses("a 9.9.9.9"), "a 198.18.0.9")
        # a later text (the system prompt, say) holds a real address equal to that stand-in
        self.assertEqual(redactor.redact_addresses("b 198.18.0.9"), "b __ADDR_1__")
        self.assertEqual(redactor.restore_addresses("a 198.18.0.9"), "a 9.9.9.9")

    # -- 4: text inside {{ }} -----------------------------------------------------------------

    def test_jinja_spans_are_masked_when_the_text_is_only_forwarded(self) -> None:
        text = "{{ ntp server 9.9.9.9 }} and 9.9.9.8"
        kept = _auto().redact_addresses(text)  # wiki notes: template syntax stays as written
        self.assertEqual(kept, "{{ ntp server 9.9.9.9 }} and 198.18.0.8")
        forwarded = _auto().redact_addresses(text, inside_jinja=True)
        self.assertNotIn("9.9.9.9", forwarded)
        self.assertEqual(forwarded, "{{ ntp server 198.18.0.9 }} and 198.18.0.8")

    # -- 5: what passes through as a mask ---------------------------------------------------------

    def test_the_pass_through_set_is_exactly_the_mask_shapes_of_reserved_space(self) -> None:
        netmasks = {str(ipaddress.IPv4Address(((1 << n) - 1) << (32 - n))) for n in range(8, 33)}
        wildcards = {str(ipaddress.IPv4Address((1 << k) - 1)) for k in range(0, 25)}
        for text in netmasks | wildcards:
            self.assertTrue(is_meaning_only(ipaddress.ip_address(text)), text)
        # reserved space only: nothing here can be a host, and a lookalike elsewhere is masked
        for text in ("0.0.0.4", "0.1.0.0", "255.0.255.0", "254.255.255.255", "1.255.255.255"):
            self.assertFalse(is_meaning_only(ipaddress.ip_address(text)), text)
        self.assertTrue(all(a.startswith(("255.", "0.")) for a in netmasks | wildcards))

    # -- 6: cuts and odd forms -----------------------------------------------------------------

    def test_cut_never_leaves_half_an_address(self) -> None:
        from workflow_steps.contact_the_ai.prompt import cut_text

        self.assertEqual(cut_text("gateway 140.1.0.15 end", 15), ("gateway ", 14))
        self.assertEqual(cut_text("short", 15), ("short", 0))
        self.assertEqual(cut_text("fe80::1:2:3:4", 8)[0], "")  # all of it could be an address
        head, omitted = cut_text("a" * 50 + " 2001:db8::1", 56)
        self.assertEqual((head, omitted), ("a" * 50 + " ", 11))

    def test_leading_zero_octets_are_hidden_not_ignored(self) -> None:
        for text in ("192.168.001.1", "10.0.0.01", "010.001.002.003"):
            with self.subTest(text):
                self.assertEqual(Redactor().redact_addresses(f"x {text} y"), "x __ADDR_1__ y")
                self.assertEqual(_auto().redact_addresses(f"x {text} y"), "x __ADDR_1__ y")

    def test_ipv6_zone_id_goes_with_the_address(self) -> None:
        self.assertEqual(Redactor().redact_addresses("if fe80::1%eth0 up"), "if __ADDR_1__ up")
        out = _auto().redact_addresses("if fe80::1%eth0 up")
        self.assertNotIn("eth0", out)
        self.assertNotIn("fe80", out)

    # -- 7: the map file ------------------------------------------------------------------------

    def test_relative_map_path_cannot_leave_the_data_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            (data / "ai").mkdir(parents=True)
            self.assertEqual(
                resolve_map_path("ai/map.yaml", data), (data / "ai" / "map.yaml").resolve()
            )
            for bad in ("../outside.yaml", "ai/../../.env", "ai/../.."):
                with self.subTest(bad), self.assertRaises(AddressMapError):
                    resolve_map_path(bad, data)
            absolute = Path(tmp) / "elsewhere.yaml"  # an absolute path is the operator's choice
            self.assertEqual(resolve_map_path(str(absolute), data), absolute)

    def test_yaml_aliases_and_bad_encoding_are_refused_with_a_map_error(self) -> None:
        with TemporaryDirectory() as tmp:
            refs = Path(tmp) / "refs.yaml"
            refs.write_text("a: &x 10.0.0.0/24\nb: *x\n")
            with self.assertRaisesRegex(AddressMapError, "aliases .* not allowed"):
                load_address_map(refs)
            binary = Path(tmp) / "binary.yaml"
            binary.write_bytes(b"10.0.0.0/24: \xff\xfe\n")
            with self.assertRaisesRegex(AddressMapError, "UTF-8"):
                load_address_map(binary)


class ExampleFileTests(unittest.TestCase):
    def test_the_shipped_example_is_valid_in_every_mode(self) -> None:
        example = (
            Path(__file__).resolve().parents[3]
            / "contributing-data"
            / "ai"
            / "address-map.example.yaml"
        )
        address_map = load_address_map(example)
        self.assertGreaterEqual(len(address_map), 2)
        validate_masking_config("map", address_map)
        validate_masking_config("auto", address_map)  # its prefixes stay out of the auto pools
        masker = build_masker("map", address_map)
        self.assertEqual(masker.mask("203.0.113.5"), "10.250.1.5")  # type: ignore[union-attr]


class StartupSettingsTests(unittest.TestCase):
    def _settings(self, **env: str):
        from core.config import Settings

        with patch.dict("os.environ", env):
            return Settings()

    def test_default_is_tokens_without_a_map(self) -> None:
        configured = self._settings()
        self.assertEqual(configured.ai_address_masking, "tokens")
        self.assertIsNone(configured.ai_address_map)

    def test_map_file_is_loaded_relative_to_the_data_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "ai").mkdir()
            (Path(tmp) / "ai" / "map.yaml").write_text("140.1.0.0/24: 192.168.178.0/24\n")
            configured = self._settings(
                DATA_DIRECTORY=tmp, AI_ADDRESS_MASKING="MAP", AI_ADDRESS_MAP_FILE="ai/map.yaml"
            )
        self.assertEqual(configured.ai_address_masking, "map")
        self.assertEqual(len(configured.ai_address_map), 1)  # type: ignore[arg-type]

    def test_bad_configuration_stops_the_start(self) -> None:
        with TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.yaml"
            bad.write_text("10.0.0.0/24: 10.0.0.0/24\n")
            for env in (
                {"AI_ADDRESS_MASKING": "bogus"},
                {"AI_ADDRESS_MASKING": "map"},  # needs the file
                {"AI_ADDRESS_MASKING": "tokens", "AI_ADDRESS_MAP_FILE": str(bad)},
                {"AI_ADDRESS_MASKING": "map", "AI_ADDRESS_MAP_FILE": str(bad)},
                {"AI_ADDRESS_MASKING": "map", "AI_ADDRESS_MAP_FILE": str(Path(tmp) / "none")},
                {"AI_ADDRESS_MASKING": "map", "AI_ADDRESS_MAP_FILE": "../outside.yaml"},
            ):
                with self.subTest(env), self.assertRaisesRegex(RuntimeError, "address masking"):
                    self._settings(**env)


if __name__ == "__main__":
    unittest.main()
