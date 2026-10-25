from pathlib import Path

import pytest

from manus_agent.device_mapping import validate_mapping
from manus_agent.ip_index import build_index, set_index
from manus_agent.registry import HandlerRegistry
from tests.data_helpers import RAW_MAPPING, SAMPLE_CSV

HANDLERS = Path(__file__).resolve().parents[1] / "handlers"


@pytest.fixture
def handle(tmp_path):
    csv_file = tmp_path / "d.csv"
    csv_file.write_text(SAMPLE_CSV)
    set_index(build_index([csv_file], ";", validate_mapping(RAW_MAPPING)))
    registry = HandlerRegistry()
    registry.load_directory(HANDLERS)
    yield registry.get("get_ip_addresses")
    set_index(None)


def test_the_handler_is_registered_from_the_shipped_directory(handle):
    assert handle is not None


def test_a_known_device_gets_only_its_own_data(handle):
    answer = handle({}, {"attributes": {"name": "device-1"}})
    assert answer["found"] is True
    assert [i["name"] for i in answer["interfaces"]] == ["eth0", "eth1"]
    assert answer["primary_ip4"]["address"] == "10.0.0.2/24"
    assert answer["problems"] == []


def test_an_unknown_device_is_found_false_not_an_error(handle):
    assert handle({}, {"attributes": {"name": "ghost"}}) == {
        "found": False,
        "device": "ghost",
        "interfaces": [],
        "problems": [],
    }


def test_the_name_attribute_can_be_changed(handle):
    answer = handle(
        {"name_attribute": "nautobot.name"}, {"attributes": {"nautobot.name": "DEVICE-1"}}
    )
    assert answer["found"] is True


@pytest.mark.parametrize(
    ("params", "inputs"),
    [
        ({}, {"attributes": {}}),
        ({}, {}),
        ({}, {"attributes": {"name": "  "}}),
        ({}, {"attributes": {"name": 5}}),
        ({"name_attribute": ""}, {"attributes": {"name": "x"}}),
    ],
)
def test_a_missing_name_or_bad_params_is_an_error(handle, params, inputs):
    with pytest.raises(ValueError):
        handle(params, inputs)


def test_without_a_loaded_index_the_handler_fails_loudly(handle):
    set_index(None)
    with pytest.raises(RuntimeError, match="not loaded"):
        handle({}, {"attributes": {"name": "device-1"}})
