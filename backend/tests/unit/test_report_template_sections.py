"""Which section ids a report template refers to (so a proposal can supply every one)."""

from __future__ import annotations

from services.reports.report_renderer import DEFAULT_TEMPLATE
from services.reports.template_sections import referenced_sections


def test_bracket_and_dot_access() -> None:
    text = (
        "{{ sections[\"devices\"].value }} and {{ sections['per-site'].table }} "
        "{{ sections.totals.first }} {{ sections [ 'x_1' ].rows }}"
    )
    result = referenced_sections(text)
    assert sorted(result.ids) == ["devices", "per-site", "totals", "x_1"]
    assert not result.uses_section_list


def test_section_list_means_any_ids_work() -> None:
    result = referenced_sections("{% for s in section_list %}{{ s.table }}{% endfor %}")
    assert result.ids == ()
    assert result.uses_section_list


def test_both_styles_and_duplicates() -> None:
    result = referenced_sections(
        '{{ sections["a"].table }}{{ sections["a"].value }}{{ section_list }}'
    )
    assert result.ids == ("a",)
    assert result.uses_section_list


def test_default_template_uses_the_list() -> None:
    result = referenced_sections(DEFAULT_TEMPLATE)
    assert result.uses_section_list and result.ids == ()


def test_no_reference_at_all() -> None:
    result = referenced_sections("# Static text for {{ report.name }}")
    assert (result.ids, result.uses_section_list) == ((), False)


def test_dynamic_lookup_cannot_be_resolved_so_it_is_not_a_fixed_id() -> None:
    result = referenced_sections("{{ sections[name].table }}")
    assert result.ids == ()
    assert result.dynamic


def test_get_with_a_literal_id_is_a_fixed_id_not_a_dynamic_lookup() -> None:
    result = referenced_sections(
        "{{ sections.get('devices').table }}{{ sections.get(\"totals\", none).value }}"
    )
    assert sorted(result.ids) == ["devices", "totals"]
    assert not result.dynamic


def test_get_with_a_variable_is_dynamic() -> None:
    result = referenced_sections("{{ sections.get(name).table }}")
    assert (result.ids, result.dynamic) == ((), True)


def test_iterating_the_dict_reaches_every_section() -> None:
    for text in (
        "{% for k, s in sections.items() %}{{ s.table }}{% endfor %}",
        "{% for s in sections.values() %}{{ s.table }}{% endfor %}",
        "{% for k in sections.keys() %}{{ k }}{% endfor %}",
    ):
        result = referenced_sections(text)
        assert (result.ids, result.uses_section_list, result.dynamic) == ((), True, False)
