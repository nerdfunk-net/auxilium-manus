"""Tests for the NiFi-style attribute expression parser."""

from __future__ import annotations

import unittest

from services.workflow_context.attribute_expression.parser import (
    Call,
    Expr,
    Literal,
    is_expression,
    parse_expression,
    split_values,
)


class IsExpressionTests(unittest.TestCase):
    def test_plain_values_are_not_expressions(self) -> None:
        for text in ("cisco_ios", "{foo}", "a:b", "{a", "x}", ""):
            self.assertFalse(is_expression(text), text)

    def test_braced_value_with_top_level_colon_is_an_expression(self) -> None:
        self.assertTrue(is_expression("{custom.value:gt(10)}"))
        self.assertTrue(is_expression("{:isEmpty()}"))

    def test_colon_inside_brackets_or_quotes_does_not_count(self) -> None:
        self.assertFalse(is_expression("{parsed.x[a=b:c].y}"))


class ParseExpressionTests(unittest.TestCase):
    def test_subject_and_single_call(self) -> None:
        expr = parse_expression("{custom.value:gt(10)}")
        self.assertEqual(
            expr,
            Expr(subject="custom.value", calls=(Call("gt", (Literal(10.0),)),)),
        )

    def test_empty_subject_means_step_attribute(self) -> None:
        expr = parse_expression("{:isEmpty()}")
        self.assertEqual(expr.subject, "")
        self.assertEqual(expr.calls[0].name, "isEmpty")

    def test_chain_and_string_argument(self) -> None:
        expr = parse_expression("{device.name:toLower():equals('lab')}")
        self.assertEqual([c.name for c in expr.calls], ["toLower", "equals"])
        self.assertEqual(expr.calls[1].args, (Literal("lab"),))

    def test_commas_and_parens_inside_quotes_stay_in_the_argument(self) -> None:
        expr = parse_expression("{x:in('a,b', \"c)d\")}")
        self.assertEqual(expr.calls[0].args, (Literal("a,b"), Literal("c)d")))

    def test_escaped_quote(self) -> None:
        expr = parse_expression(r"{x:equals('it\'s')}")
        self.assertEqual(expr.calls[0].args, (Literal("it's"),))

    def test_subject_may_contain_filter_brackets_and_placeholders(self) -> None:
        expr = parse_expression("{parsed.k.acl[name={custom.n}].style:equals('std')}")
        self.assertEqual(expr.subject, "parsed.k.acl[name={custom.n}].style")

    def test_nested_reference_argument(self) -> None:
        expr = parse_expression("{custom.a:equals({custom.b})}")
        arg = expr.calls[0].args[0]
        self.assertEqual(arg, Expr(subject="custom.b", calls=()))

    def test_boolean_combinator_takes_a_nested_expression(self) -> None:
        expr = parse_expression("{custom.a:gt(1):and({custom.a:lt(5)})}")
        self.assertEqual(expr.calls[1].name, "and")
        self.assertIsInstance(expr.calls[1].args[0], Expr)

    def test_booleans_and_numbers(self) -> None:
        expr = parse_expression("{x:substring(1, 3):equals('a')}")
        self.assertEqual(expr.calls[0].args, (Literal(1.0), Literal(3.0)))

    def test_whitespace_is_tolerated(self) -> None:
        expr = parse_expression("{ custom.value : gt( 10 ) }")
        self.assertEqual(expr.subject, "custom.value")

    def test_unknown_function_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown function 'bogus'"):
            parse_expression("{x:bogus()}")

    def test_wrong_arity_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "gt"):
            parse_expression("{x:gt()}")
        with self.assertRaisesRegex(ValueError, "isEmpty"):
            parse_expression("{x:isEmpty(1)}")

    def test_final_call_must_be_boolean(self) -> None:
        with self.assertRaisesRegex(ValueError, "boolean"):
            parse_expression("{x:toLower()}")
        with self.assertRaisesRegex(ValueError, "boolean"):
            parse_expression("{x:length()}")

    def test_state_function_must_come_first(self) -> None:
        with self.assertRaisesRegex(ValueError, "first"):
            parse_expression("{x:trim():isEmpty()}")

    def test_count_must_be_first_and_needs_a_comparison_to_be_boolean(self) -> None:
        self.assertEqual(
            [c.name for c in parse_expression("{x:count():gt(2)}").calls], ["count", "gt"]
        )
        with self.assertRaisesRegex(ValueError, "first"):
            parse_expression("{x:trim():count():gt(2)}")
        with self.assertRaisesRegex(ValueError, "boolean"):
            parse_expression("{x:count()}")

    def test_state_function_may_be_negated(self) -> None:
        expr = parse_expression("{x:isEmpty():not()}")
        self.assertEqual([c.name for c in expr.calls], ["isEmpty", "not"])

    def test_unterminated_input_reports_a_position(self) -> None:
        with self.assertRaisesRegex(ValueError, "position"):
            parse_expression("{x:equals('a'")
        with self.assertRaisesRegex(ValueError, "position"):
            parse_expression("{x:equals('a)}")

    def test_trailing_text_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "position"):
            parse_expression("{x:isEmpty()} extra")

    def test_empty_regex_pattern_is_rejected_but_other_patterns_are_not_compiled(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-empty pattern"):
            parse_expression("{x:find('')}")
        # An invalid pattern is reported per device by the isolated runner, never compiled here.
        self.assertEqual(parse_expression("{x:matches('(')}").calls[0].args, (Literal("("),))

    def test_deep_nesting_is_a_value_error_not_a_recursion_error(self) -> None:
        text = "{a:exists()}"
        for _ in range(400):
            text = "{a:exists():and(" + text + ")}"
        with self.assertRaisesRegex(ValueError, "nested"):
            parse_expression(text)

    def test_moderate_nesting_still_parses(self) -> None:
        text = "{a:exists()}"
        for _ in range(8):
            text = "{a:exists():and(" + text + ")}"
        self.assertEqual(parse_expression(text).calls[1].name, "and")

    def test_string_may_end_in_an_escaped_backslash(self) -> None:
        expr = parse_expression(r"{x:equals('foo\\')}")
        self.assertEqual(expr.calls[0].args, (Literal("foo\\"),))

    def test_double_backslash_is_one_backslash_and_unknown_escapes_are_kept(self) -> None:
        self.assertEqual(
            parse_expression(r"{x:find('a\\d')}").calls[0].args, (Literal("a\\d"),)
        )
        self.assertEqual(parse_expression(r"{x:find('a\d')}").calls[0].args, (Literal(r"a\d"),))


class SplitValuesTests(unittest.TestCase):
    def test_plain_comma_list(self) -> None:
        self.assertEqual(split_values("cisco_ios, ios"), ["cisco_ios", "ios"])

    def test_commas_inside_expression_are_kept(self) -> None:
        self.assertEqual(
            split_values("{x:in('a','b')}, plain, {:gt(1)}"),
            ["{x:in('a','b')}", "plain", "{:gt(1)}"],
        )

    def test_escaped_quote_does_not_end_the_quoted_part(self) -> None:
        self.assertEqual(
            split_values(r"{x:in('a\',b','c')}, plain"),
            [r"{x:in('a\',b','c')}", "plain"],
        )

    def test_blank_entries_are_dropped(self) -> None:
        self.assertEqual(split_values(" , a ,, "), ["a"])


if __name__ == "__main__":
    unittest.main()
