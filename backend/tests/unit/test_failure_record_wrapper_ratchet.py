"""Guard 3 (P-E, W3a-10): a failure recorded through a wrapper names its cause.

``test_device_error_failure_ratchet.py`` counts ``DeviceError(...)`` calls without ``failure=``, but
most steps build the error inside a small wrapper (``_fail_device``, ``_device_failure``,
``mark_device_failed``, ...), where the ratchet cannot see it. This one counts the calls of those
wrappers (and the runner's ``Fail(code, message)``) that give a ``code`` and no ``failure``. The
legacy sites are pinned per file and may only fall; never raise a number or add a file. When a
count reaches zero, delete the entry.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

STEPS_ROOT = Path(__file__).resolve().parents[2] / "workflow_steps"
HOME = "workflow_steps/common/device_outcomes.py"
# ``device_file_upload._failed`` builds a checksum-check result, not a device error.
NOT_DEVICE_ERRORS = frozenset({"workflow_steps/common/device_file_upload.py"})
_WRAPPER = re.compile(
    r"^(_?fail(ed)?_device|_fail(ed)?|_?failed_device|_device_failure|_mark_failed"
    r"|mark_device_failed|_refusal)$"
)
_EXTRA = frozenset({"_failed", "_fail"})

LEGACY_WITHOUT_FAILURE: dict[str, int] = {
    # A verdict and a device-reported state with no kind in the vocabulary that fits yet.
    "workflow_steps/configure_replace_config/executor.py": 2,
}


def _calls_without_failure() -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in sorted(STEPS_ROOT.rglob("*.py")):
        rel = path.relative_to(STEPS_ROOT.parent).as_posix()
        if rel == HOME or rel in NOT_DEVICE_ERRORS:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            is_fail = name == "Fail"  # the runner's ``Fail(code, message, failure=None)``
            if not (is_fail or _WRAPPER.match(name) or name in _EXTRA):
                continue
            keywords = {kw.arg for kw in node.keywords}
            if is_fail:
                gives_code = bool(node.args) or "code" in keywords
                has_failure = "failure" in keywords or len(node.args) >= 3
            else:
                gives_code = "code" in keywords or len(node.args) >= 3
                # ``_fail(device, node_id, code, message, failure)``: failure as the fifth argument.
                has_failure = "failure" in keywords or (name in _EXTRA and len(node.args) >= 5)
            if gives_code and not has_failure and None not in keywords:
                counts[rel] += 1
    return counts


def test_no_new_wrapper_failure_without_a_record() -> None:
    actual = _calls_without_failure()
    grown = {
        f: (LEGACY_WITHOUT_FAILURE.get(f, 0), n)
        for f, n in actual.items()
        if n > LEGACY_WITHOUT_FAILURE.get(f, 0)
    }
    assert not grown, (
        "a failure recorded through a wrapper has a code but no FailureInfo; pass failure= "
        f"(allowed, found): {grown}"
    )


def test_wrapper_ratchet_list_is_not_stale() -> None:
    actual = _calls_without_failure()
    stale = {
        f: (n, actual.get(f, 0)) for f, n in LEGACY_WITHOUT_FAILURE.items() if actual.get(f, 0) < n
    }
    assert not stale, f"lower these entries in LEGACY_WITHOUT_FAILURE (listed, found): {stale}"
