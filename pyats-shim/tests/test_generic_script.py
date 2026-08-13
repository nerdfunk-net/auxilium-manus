"""Tests for RunRequestedOperation's learn branch in generic_script.py.

Guarded by importorskip: this module does `from pyats import aetest` at import
time, which isn't installed in every environment that runs the rest of the
shim's test suite (see requirements-dev.txt) -- it's expected to run inside
the shim's own container/venv, where pyats[full] is installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pyats")

from app.job_scripts.generic_script import CONNECT_MARKER, RunRequestedOperation  # noqa: E402


class _FakeOps:
    def __init__(self, data: dict) -> None:
        self._data = data

    def to_dict(self) -> dict:
        return self._data


class _FakeDevice:
    def __init__(self, *, learn_results: dict, learn_errors: dict | None = None) -> None:
        self._learn_results = learn_results
        self._learn_errors = learn_errors or {}

    def learn(self, feature: str) -> _FakeOps:
        if feature in self._learn_errors:
            raise self._learn_errors[feature]
        return _FakeOps(self._learn_results[feature])


class _FakeTestbed:
    def __init__(self, devices: dict) -> None:
        self.devices = devices


def test_learn_operation_stores_ops_to_dict_per_feature():
    device = _FakeDevice(learn_results={"bgp": {"info": {"instance": {}}}, "interface": {"Gi0/0": {}}})
    testbed = _FakeTestbed({"dev1": device})
    results = {"dev1": {"success": True, "error": None, "commands": {}}}

    RunRequestedOperation().run_commands(
        testbed=testbed, operation="learn", commands=["bgp", "interface"], results=results
    )

    assert results["dev1"]["commands"]["bgp"]["parsed"] == {"info": {"instance": {}}}
    assert results["dev1"]["commands"]["interface"]["parsed"] == {"Gi0/0": {}}
    assert results["dev1"]["commands"]["bgp"]["error"] is None


def test_learn_operation_isolates_per_feature_failure():
    device = _FakeDevice(
        learn_results={"interface": {"Gi0/0": {}}},
        learn_errors={"vrf": RuntimeError("not supported on this platform")},
    )
    testbed = _FakeTestbed({"dev1": device})
    results = {"dev1": {"success": True, "error": None, "commands": {}}}

    RunRequestedOperation().run_commands(
        testbed=testbed, operation="learn", commands=["vrf", "interface"], results=results
    )

    assert results["dev1"]["commands"]["interface"]["parsed"] == {"Gi0/0": {}}
    assert results["dev1"]["commands"]["interface"]["error"] is None
    assert "not supported on this platform" in results["dev1"]["commands"]["vrf"]["error"]
    assert results["dev1"]["commands"]["vrf"]["parsed"] is None


def test_learn_operation_treats_none_result_as_no_error():
    device = _FakeDevice(learn_results={"all": None})
    testbed = _FakeTestbed({"dev1": device})
    results = {"dev1": {"success": True, "error": None, "commands": {}}}

    RunRequestedOperation().run_commands(
        testbed=testbed, operation="learn", commands=["all"], results=results
    )

    assert results["dev1"]["commands"]["all"]["parsed"] is None
    assert results["dev1"]["commands"]["all"]["error"] is None


def test_connect_marker_import_still_works():
    # Regression guard for the ModuleNotFoundError hit earlier this session:
    # generic_script.py must define CONNECT_MARKER locally, not import it
    # from app.log_markers (unreachable from this file's runtime sys.path).
    assert CONNECT_MARKER == "[pyats-connect]"
