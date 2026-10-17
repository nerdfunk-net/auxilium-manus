"""Tests for evaluating attribute expressions against a device."""

from __future__ import annotations

import unittest

from models.workflow_context import Capability, DeviceContext, DeviceError, DeviceStatus
from services.workflow_context.attribute_expression.evaluator import (
    RegexLookup,
    RegexUnavailableError,
    evaluate,
)
from services.workflow_context.attribute_expression.parser import parse_expression


def _device(**bags: dict) -> DeviceContext:
    return DeviceContext(
        id="d1",
        name="LAB-sw1",
        hostname="lab-sw1",
        network_driver="cisco_ios",
        attribute_bags=bags,
        parsed={"lst": [1, 2], "empty_lst": []},
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


def _check(
    text: str,
    device: DeviceContext | None = None,
    *,
    default_path: str = "device.name",
    regex: RegexLookup | None = None,
    error: DeviceError | None = None,
) -> bool:
    return evaluate(
        parse_expression(text),
        device or _device(custom={"value": "12", "word": "Hello", "blank": "", "nul": None}),
        default_path=default_path,
        regex=regex or RegexLookup(),
        error=error,
    )


class StateFunctionTests(unittest.TestCase):
    def test_exists_isempty_isnull_isabsent(self) -> None:
        self.assertTrue(_check("{custom.value:exists()}"))
        self.assertFalse(_check("{custom.blank:exists()}"))
        self.assertTrue(_check("{custom.blank:isEmpty()}"))
        self.assertTrue(_check("{custom.nul:isNull()}"))
        self.assertTrue(_check("{custom.missing:isAbsent()}"))
        self.assertFalse(_check("{custom.value:isAbsent()}"))

    def test_lists_use_state_functions(self) -> None:
        self.assertTrue(_check("{parsed.lst:exists()}"))
        self.assertTrue(_check("{parsed.empty_lst:isEmpty()}"))

    def test_negated_state(self) -> None:
        self.assertTrue(_check("{custom.value:isEmpty():not()}"))

    def test_empty_subject_uses_default_path(self) -> None:
        self.assertTrue(_check("{:exists()}", default_path="custom.value"))
        self.assertTrue(_check("{:isAbsent()}", default_path="custom.nope"))


class CompareTests(unittest.TestCase):
    def test_numeric(self) -> None:
        self.assertTrue(_check("{custom.value:gt(10)}"))
        self.assertTrue(_check("{custom.value:ge(12)}"))
        self.assertFalse(_check("{custom.value:lt(12)}"))
        self.assertTrue(_check("{custom.value:le(12)}"))

    def test_non_numeric_comparison_is_false_not_an_error(self) -> None:
        self.assertFalse(_check("{custom.word:gt(1)}"))
        self.assertFalse(_check("{custom.missing:gt(1)}"))

    def test_string_comparisons(self) -> None:
        self.assertTrue(_check("{device.name:equalsIgnoreCase('lab-SW1')}"))
        self.assertFalse(_check("{device.name:equals('lab-sw1')}"))
        self.assertTrue(_check("{device.name:startsWith('LAB')}"))
        self.assertTrue(_check("{device.name:endsWith('sw1')}"))
        self.assertTrue(_check("{device.name:contains('-sw')}"))
        self.assertTrue(_check("{custom.word:in('x', 'Hello')}"))
        self.assertFalse(_check("{custom.word:in('x', 'y')}"))

    def test_compare_against_another_attribute(self) -> None:
        self.assertTrue(_check("{custom.value:equals({custom.value})}"))
        self.assertFalse(_check("{custom.value:equals({custom.word})}"))
        self.assertFalse(_check("{custom.value:equals({custom.missing})}"))

    def test_missing_subject_is_false_for_string_functions(self) -> None:
        self.assertFalse(_check("{custom.missing:equals('a')}"))
        self.assertFalse(_check("{custom.missing:contains('a')}"))


class TransformTests(unittest.TestCase):
    def test_case_and_trim(self) -> None:
        self.assertTrue(_check("{custom.word:toLower():equals('hello')}"))
        self.assertTrue(_check("{custom.word:toUpper():equals('HELLO')}"))

    def test_length_and_substring(self) -> None:
        self.assertTrue(_check("{custom.word:length():equals(5)}"))
        self.assertTrue(_check("{custom.word:substring(0, 2):equals('He')}"))
        self.assertTrue(_check("{custom.word:substring(3):equals('lo')}"))

    def test_replace_append_prepend(self) -> None:
        self.assertTrue(_check("{custom.word:replace('l','L'):equals('HeLLo')}"))
        self.assertTrue(_check("{custom.word:append('!'):equals('Hello!')}"))
        self.assertTrue(_check("{custom.word:prepend('>'):equals('>Hello')}"))

    def test_arithmetic(self) -> None:
        self.assertTrue(_check("{custom.value:plus(3):equals(15)}"))
        self.assertTrue(_check("{custom.value:minus(2):lt(11)}"))
        self.assertTrue(_check("{custom.value:multiply(2):equals(24)}"))
        self.assertTrue(_check("{custom.value:mod(5):equals(2)}"))
        self.assertFalse(_check("{custom.value:mod(0):equals(0)}"))


class BooleanTests(unittest.TestCase):
    def test_and_or_not(self) -> None:
        self.assertTrue(_check("{custom.value:gt(10):and({custom.value:lt(20)})}"))
        self.assertFalse(_check("{custom.value:gt(10):and({custom.value:lt(11)})}"))
        self.assertTrue(_check("{custom.value:lt(1):or({custom.word:equals('Hello')})}"))
        self.assertTrue(_check("{custom.value:lt(1):not()}"))


class RegexTests(unittest.TestCase):
    def test_first_pass_records_requests_and_returns_false(self) -> None:
        lookup = RegexLookup()
        self.assertFalse(_check("{device.name:matches('LAB-.*')}", regex=lookup))
        self.assertEqual(lookup.pending, {("LAB-sw1", "LAB-.*", "full")})

    def test_second_pass_uses_results(self) -> None:
        lookup = RegexLookup(results={("LAB-sw1", "LAB-.*", "full"): True})
        self.assertTrue(_check("{device.name:matches('LAB-.*')}", regex=lookup))
        self.assertEqual(lookup.pending, set())

    def test_find_mode_key(self) -> None:
        lookup = RegexLookup()
        _check("{device.name:toLower():find('sw\\d')}", regex=lookup)
        self.assertEqual(lookup.pending, {("lab-sw1", "sw\\d", "find")})

    def test_missing_subject_does_not_request_a_match(self) -> None:
        lookup = RegexLookup()
        self.assertFalse(_check("{custom.missing:matches('a')}", regex=lookup))
        self.assertEqual(lookup.pending, set())

    def test_both_sides_of_or_are_evaluated_so_one_pass_collects_everything(self) -> None:
        lookup = RegexLookup()
        _check(
            "{device.name:matches('a'):or({device.name:matches('b')})}",
            regex=lookup,
        )
        self.assertEqual(len(lookup.pending), 2)


class CountTests(unittest.TestCase):
    def _device(self) -> DeviceContext:
        device = _device(custom={"word": "Hello", "blank": "", "nul": None, "d": {"a": 1, "b": 2}})
        return device.model_copy(
            update={
                "parsed": {
                    "k": {
                        "show version": {
                            "parsed": [{"serial": ["serial1", "serial2"], "one": ["only"]}]
                        }
                    },
                    "empty_lst": [],
                }
            }
        )

    def test_counts_list_items_for_textfsm_style_paths(self) -> None:
        device = self._device()
        path = "parsed.k.show version.parsed[0]"
        self.assertTrue(_check("{" + path + ".serial:count():gt(1)}", device))
        self.assertTrue(_check("{" + path + ".serial:count():equals(2)}", device))
        self.assertFalse(_check("{" + path + ".serial:count():gt(2)}", device))
        self.assertTrue(_check("{" + path + ".serial:count():lt(3)}", device))

    def test_one_item_list_counts_one_not_the_unwrapped_scalar_length(self) -> None:
        device = self._device()
        self.assertTrue(_check("{parsed.k.show version.parsed[0].one:count():equals(1)}", device))

    def test_empty_null_absent_count_zero(self) -> None:
        device = self._device()
        for path in ("parsed.empty_lst", "custom.blank", "custom.nul", "custom.nope"):
            self.assertTrue(_check("{" + path + ":count():equals(0)}", device), path)

    def test_scalar_counts_one_and_dict_counts_keys(self) -> None:
        device = self._device()
        self.assertTrue(_check("{custom.word:count():equals(1)}", device))
        self.assertTrue(_check("{custom.d:count():equals(2)}", device))

    def test_empty_subject_uses_the_step_attribute_path(self) -> None:
        device = self._device()
        self.assertTrue(
            _check(
                "{:count():ge(2)}",
                device,
                default_path="parsed.k.show version.parsed[0].serial",
            )
        )

    def test_count_sees_the_device_error_like_the_state_functions(self) -> None:
        error = DeviceError(node_id="n1", step_id="s", code="c1", message="m")
        self.assertTrue(_check("{error.code:exists()}", error=error))
        self.assertTrue(_check("{error.code:count():equals(1)}", error=error))
        self.assertTrue(_check("{error.code:count():equals(0)}"))  # no error: absent -> 0

    def test_count_expands_a_placeholder_that_needs_the_device_error(self) -> None:
        error = DeviceError(node_id="n1", step_id="s", code="c1", message="m")
        device = self._device().model_copy(
            update={
                "parsed": {
                    "rows": [
                        {"code": "c1", "items": ["a", "b"]},
                        {"code": "c2", "items": ["x"]},
                    ]
                }
            }
        )
        path = "parsed.rows[code={error.code}].items"
        self.assertTrue(_check("{" + path + ":exists()}", device, error=error))
        self.assertTrue(_check("{" + path + ":count():equals(2)}", device, error=error))

    def test_count_and_isempty_agree_on_a_one_item_blank_list(self) -> None:
        # A one-item list of a scalar is that scalar (TextFSM "Value List"), for both functions.
        for blank in ("", "   "):
            device = _device(custom={"one": [blank]})
            self.assertTrue(_check("{custom.one:isEmpty()}", device), repr(blank))
            self.assertTrue(_check("{custom.one:count():equals(0)}", device), repr(blank))
        # [None] unwraps to null: isNull() is the matching state, and it counts 0 as well.
        device = _device(custom={"one": [None]})
        self.assertTrue(_check("{custom.one:isNull()}", device))
        self.assertTrue(_check("{custom.one:count():equals(0)}", device))

    def test_one_item_list_of_a_real_value_counts_one_and_is_not_empty(self) -> None:
        device = _device(custom={"one": ["only"]})
        self.assertFalse(_check("{custom.one:isEmpty()}", device))
        self.assertTrue(_check("{custom.one:count():equals(1)}", device))

    def test_two_blank_items_are_still_two_items(self) -> None:
        device = _device(custom={"two": ["", ""]})
        self.assertTrue(_check("{custom.two:count():equals(2)}", device))

    def test_sealed_secret_counts_as_one_item(self) -> None:
        from core.crypto import EncryptionService
        from services.workflow_context.secret_fields import seal_secret

        enc = EncryptionService("test-secret-key-for-expression")
        device = _device(custom={"key": seal_secret("s3cret", encryption=enc)})
        self.assertTrue(_check("{custom.key:count():equals(1)}", device))


class RegexUnavailableTests(unittest.TestCase):
    def test_invalid_answer_raises_a_message_without_pattern_or_text(self) -> None:
        lookup = RegexLookup(results={("LAB-sw1", "(", "full"): "invalid"})
        with self.assertRaises(RegexUnavailableError) as caught:
            _check("{device.name:matches('(')}", regex=lookup)
        self.assertEqual(caught.exception.code, "invalid_regular_expression")
        self.assertNotIn("LAB-sw1", caught.exception.message)

    def test_stopped_answer_has_its_own_code(self) -> None:
        lookup = RegexLookup(results={("LAB-sw1", "x", "full"): "stopped"})
        with self.assertRaises(RegexUnavailableError) as caught:
            _check("{device.name:matches('x')}", regex=lookup)
        self.assertEqual(caught.exception.code, "regular_expression_stopped")

    def test_collecting_lookup_reads_a_bad_answer_as_false(self) -> None:
        lookup = RegexLookup(results={("LAB-sw1", "(", "full"): "invalid"}, strict=False)
        self.assertFalse(_check("{device.name:matches('(')}", regex=lookup))


class TransformLimitTests(unittest.TestCase):
    def test_replace_with_empty_search_text_is_no_value(self) -> None:
        self.assertFalse(_check("{custom.word:replace('', 'x'):length():gt(0)}"))
        self.assertFalse(_check("{custom.word:replace('', 'x'):equals('xHx')}"))

    def test_replace_that_would_exceed_the_cap_is_no_value(self) -> None:
        big = "x" * 600_000
        device = _device(custom={"big": big})
        self.assertFalse(_check("{custom.big:replace('x', 'yy'):length():gt(0)}", device))
        self.assertTrue(_check("{custom.big:replace('x', 'y'):length():gt(0)}", device))

    def test_append_that_would_exceed_the_cap_is_no_value(self) -> None:
        device = _device(custom={"big": "x" * 600_000})
        self.assertFalse(_check("{custom.big:append({custom.big}):length():gt(0)}", device))


class SecretTests(unittest.TestCase):
    def test_sealed_secret_is_never_revealed_to_string_functions(self) -> None:
        from core.crypto import EncryptionService
        from services.workflow_context.secret_fields import seal_secret

        enc = EncryptionService("test-secret-key-for-expression")
        device = _device(custom={"key": seal_secret("s3cret", encryption=enc)})
        self.assertTrue(_check("{custom.key:exists()}", device))
        self.assertFalse(_check("{custom.key:equals('s3cret')}", device))


if __name__ == "__main__":
    unittest.main()
