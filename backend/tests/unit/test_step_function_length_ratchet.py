"""Guard 7 (W0, OPEN_TODOS Q1/Q10): long functions in ``workflow_steps`` may only disappear.

The project rule is "functions under 50 lines". A function counts as long when it spans more
than ``MAX_LINES`` lines from ``def`` to its last line (docstring included, decorators not).
The legacy long functions are pinned per file; the count may only fall. Splitting one is
welcome; adding one, or growing a short one past the limit, fails here. When a count falls,
lower the entry (the stale check names it); at zero, delete it.
"""

from __future__ import annotations

import ast
import textwrap
from collections import Counter
from pathlib import Path

import pytest

STEPS_ROOT = Path(__file__).resolve().parents[2] / "workflow_steps"
MAX_LINES = 50

LEGACY_LONG_FUNCTIONS: dict[str, int] = {
    "workflow_steps/add_ip_to_nautobot/executor.py": 2,
    "workflow_steps/add_nautobot_metadata/executor.py": 1,
    "workflow_steps/add_pyats_testbed/executor.py": 1,
    "workflow_steps/add_to_ise/executor.py": 2,
    "workflow_steps/add_to_ise/fields.py": 1,
    "workflow_steps/add_to_nautobot/executor.py": 3,
    "workflow_steps/backup_aci_config/executor.py": 1,
    "workflow_steps/batfish_acl_check/executor.py": 1,
    "workflow_steps/batfish_extract_facts/executor.py": 1,
    "workflow_steps/batfish_init_snapshot/executor.py": 1,
    "workflow_steps/batfish_path_check/executor.py": 1,
    "workflow_steps/batfish_routing_table/executor.py": 1,
    "workflow_steps/batfish_validate_facts/executor.py": 2,
    "workflow_steps/check_nautobot_job/executor.py": 1,
    "workflow_steps/collect_client_data/collector.py": 1,
    "workflow_steps/collect_client_data/executor.py": 2,
    "workflow_steps/collect_statistics/executor.py": 1,
    "workflow_steps/common/attribute_defaults.py": 1,
    "workflow_steps/common/attribute_merge.py": 1,
    "workflow_steps/common/attribute_write.py": 1,
    "workflow_steps/common/batfish_combined_facts.py": 2,
    "workflow_steps/common/batfish_properties.py": 2,
    "workflow_steps/common/config_push.py": 1,
    "workflow_steps/common/content_resolver.py": 1,
    "workflow_steps/common/content_step.py": 1,
    "workflow_steps/common/controller_inventory.py": 1,
    "workflow_steps/common/device_builders.py": 2,
    "workflow_steps/common/device_file_upload.py": 1,
    "workflow_steps/common/device_list.py": 2,
    "workflow_steps/common/device_runner.py": 1,
    "workflow_steps/common/fact_entries.py": 1,
    "workflow_steps/common/git_workflow_step.py": 1,
    "workflow_steps/common/interface_payload.py": 1,
    "workflow_steps/common/nautobot_object_update.py": 3,
    "workflow_steps/common/partial_outcomes.py": 1,
    "workflow_steps/common/pyats_batch.py": 1,
    "workflow_steps/common/redundancy_groups.py": 1,
    "workflow_steps/common/secret_manager_step.py": 1,
    "workflow_steps/common/value_expression.py": 1,
    "workflow_steps/compare_aci_subnets/compare.py": 1,
    "workflow_steps/compare_aci_subnets/executor.py": 1,
    "workflow_steps/compare_data/executor.py": 3,
    "workflow_steps/compare_pyats_snapshot/executor.py": 5,
    "workflow_steps/config_to_attributes/executor.py": 2,
    "workflow_steps/configure_replace_config/diff_checks.py": 2,
    "workflow_steps/configure_replace_config/executor.py": 3,
    "workflow_steps/contact_the_ai/executor.py": 1,
    "workflow_steps/decrypt_attribute/executor.py": 1,
    "workflow_steps/deploy_rendered_template/executor.py": 2,
    "workflow_steps/discover_network/crawler.py": 1,
    "workflow_steps/discover_network/executor.py": 2,
    "workflow_steps/encrypt_attribute/executor.py": 1,
    "workflow_steps/enrich_attributes/executor.py": 1,
    "workflow_steps/exists_in_nautobot/executor.py": 1,
    "workflow_steps/filter_output/executor.py": 1,
    "workflow_steps/find_aci_endpoints/executor.py": 1,
    "workflow_steps/from_change_request/executor.py": 1,
    "workflow_steps/generate_password/executor.py": 1,
    "workflow_steps/get_batfish_devices/executor.py": 1,
    "workflow_steps/get_catalyst_center_client_data/executor.py": 2,
    "workflow_steps/get_catalyst_center_configs/executor.py": 1,
    "workflow_steps/get_device_configs/executor.py": 2,
    "workflow_steps/get_from_agent/executor.py": 1,
    "workflow_steps/get_from_config/executor.py": 1,
    "workflow_steps/get_from_db/executor.py": 1,
    "workflow_steps/get_from_user/executor.py": 1,
    "workflow_steps/get_git_devices/executor.py": 1,
    "workflow_steps/get_ise_devices/executor.py": 2,
    "workflow_steps/get_ise_tacacs_key/executor.py": 1,
    "workflow_steps/get_nautobot_attributes/executor.py": 1,
    "workflow_steps/get_nautobot_devices/executor.py": 1,
    "workflow_steps/get_next_free_ip/executor.py": 1,
    "workflow_steps/get_pyats_running_config/executor.py": 1,
    "workflow_steps/get_pyats_snapshot/executor.py": 2,
    "workflow_steps/get_virtual_chassis/executor.py": 1,
    "workflow_steps/get_virtual_chassis/stack.py": 1,
    "workflow_steps/git_push/executor.py": 1,
    "workflow_steps/list_contains/executor.py": 1,
    "workflow_steps/log_attributes/executor.py": 1,
    "workflow_steps/log_message/executor.py": 1,
    "workflow_steps/login_successful/executor.py": 2,
    "workflow_steps/merge_config/executor.py": 2,
    "workflow_steps/notify/executor.py": 1,
    "workflow_steps/notify_mattermost/executor.py": 1,
    "workflow_steps/notify_on_error/executor.py": 1,
    "workflow_steps/open_change_request/executor.py": 1,
    "workflow_steps/parse_cisco_config/executor.py": 1,
    "workflow_steps/reachable/executor.py": 1,
    "workflow_steps/read_config/executor.py": 2,
    "workflow_steps/read_from_file/executor.py": 1,
    "workflow_steps/remove_from_nautobot/executor.py": 2,
    "workflow_steps/render_jinja_template/executor.py": 2,
    "workflow_steps/route_on_attribute/executor.py": 2,
    "workflow_steps/route_on_content/executor.py": 1,
    "workflow_steps/route_to_agent/executor.py": 1,
    "workflow_steps/run_catalyst_center_command/executor.py": 3,
    "workflow_steps/run_command/config_mode.py": 1,
    "workflow_steps/run_command/enrichment.py": 2,
    "workflow_steps/run_command/executor.py": 1,
    "workflow_steps/send_mail/executor.py": 1,
    "workflow_steps/set_default_attributes/executor.py": 1,
    "workflow_steps/start_nautobot_job/executor.py": 3,
    "workflow_steps/start_workflow/executor.py": 3,
    "workflow_steps/store_artifact/executor.py": 2,
    "workflow_steps/store_for_report/executor.py": 1,
    "workflow_steps/store_in_db/executor.py": 2,
    "workflow_steps/undefined_and_unused/executor.py": 2,
    "workflow_steps/update_attribute/executor.py": 1,
    "workflow_steps/update_config_context/executor.py": 3,
    "workflow_steps/update_config_context/json_object_path.py": 1,
    "workflow_steps/update_content/executor.py": 1,
    "workflow_steps/update_ise_tacacs_key/executor.py": 2,
    "workflow_steps/update_nautobot_device/executor.py": 3,
    "workflow_steps/update_nautobot_ip/executor.py": 1,
    "workflow_steps/update_nautobot_ip/interfaces_mode.py": 2,
    "workflow_steps/update_nautobot_prefix/executor.py": 1,
    "workflow_steps/update_nautobot_vlan/executor.py": 1,
    "workflow_steps/upload_binary/executor.py": 2,
    "workflow_steps/upload_config/executor.py": 2,
}


def long_functions_in(source: str) -> list[str]:
    """Names of the functions (nested and methods included) longer than ``MAX_LINES``."""
    return [
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.end_lineno is not None
        and node.end_lineno - node.lineno + 1 > MAX_LINES
    ]


def _long_functions() -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in sorted(STEPS_ROOT.rglob("*.py")):
        if found := long_functions_in(path.read_text()):
            counts[path.relative_to(STEPS_ROOT.parent).as_posix()] = len(found)
    return counts


def test_no_new_long_function() -> None:
    grown = {
        f: (LEGACY_LONG_FUNCTIONS.get(f, 0), n)
        for f, n in _long_functions().items()
        if n > LEGACY_LONG_FUNCTIONS.get(f, 0)
    }
    assert not grown, (
        f"function longer than {MAX_LINES} lines added or grown past the limit; split it "
        f"(allowed, found): {grown}"
    )


def test_ratchet_list_is_not_stale() -> None:
    actual = _long_functions()
    stale = {
        f: (n, actual.get(f, 0)) for f, n in LEGACY_LONG_FUNCTIONS.items() if actual.get(f, 0) < n
    }
    assert not stale, f"lower these entries (listed, found); delete at zero: {stale}"


def _function(name: str, lines: int, header: str = "def") -> str:
    """A function of exactly *lines* lines: the ``def`` line plus ``lines - 1`` statements."""
    return f"{header} {name}():\n" + "".join("    x = 1\n" for _ in range(lines - 1))


@pytest.mark.parametrize("header", ["def", "async def"])
def test_the_limit_is_fifty_lines_from_def_to_the_last_line(header: str) -> None:
    assert long_functions_in(_function("f", MAX_LINES, header)) == []
    assert long_functions_in(_function("f", MAX_LINES + 1, header)) == ["f"]


def test_methods_and_nested_functions_count() -> None:
    inner = textwrap.indent(_function("m", MAX_LINES + 1), "    ")

    assert long_functions_in("class C:\n" + inner) == ["m"]
    assert long_functions_in("def outer():\n" + inner) == ["outer", "m"]


def test_decorators_do_not_count() -> None:
    assert long_functions_in("@a\n@b\n@c\n" + _function("f", MAX_LINES)) == []
