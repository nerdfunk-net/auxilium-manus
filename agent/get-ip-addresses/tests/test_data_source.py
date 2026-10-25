import contextlib
import io
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from manus_agent.data_source import DataSourceError, load_index
from manus_agent.ip_index import get_index, set_index
from manus_agent.main import main
from tests.data_helpers import commit, make_origin, raw_config
from tests.helpers import SECRET


def write_config(tmp_path, origin, **overrides):
    raw = raw_config(f"file://{origin}")
    raw["source"].update(overrides)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw))
    return {
        "MANUS_AGENT_DATA_CONFIG": str(path),
        "MANUS_AGENT_STATE_DIR": str(tmp_path / "state"),
        "MANUS_AGENT_ALLOW_FILE_URLS": "1",
    }


def test_startup_pulls_and_caches_and_a_restart_sees_new_data(tmp_path):
    origin = make_origin(tmp_path)
    env = write_config(tmp_path, origin)
    assert load_index(env).lookup("device-1") is not None
    assert load_index(env).lookup("device-9") is None
    commit(
        origin,
        {
            "ips/more.csv": "name;interface_name;interface_address;is_primary;namespace\n"
            "device-9;e0;10.9.9.9/24;true;Global\n"
        },
        "add",
    )
    assert load_index(env).lookup("device-9") is not None


def test_files_above_the_limits_are_fatal(tmp_path, monkeypatch):
    env = write_config(tmp_path, make_origin(tmp_path))
    monkeypatch.setattr("manus_agent.ip_index.MAX_TOTAL_BYTES", 10)
    with pytest.raises(DataSourceError, match="above the limit"):
        load_index(env)
    monkeypatch.setattr("manus_agent.ip_index.MAX_TOTAL_BYTES", 10**9)
    monkeypatch.setattr("manus_agent.ip_index.MAX_TOTAL_ROWS", 1)
    with pytest.raises(DataSourceError, match="more than 1 lines"):
        load_index(env)


def test_no_matching_file_is_fatal(tmp_path):
    env = write_config(tmp_path, make_origin(tmp_path), filename_pattern="*.nothing")
    with pytest.raises(DataSourceError, match="no file matching"):
        load_index(env)


def test_files_without_devices_are_fatal(tmp_path):
    origin = make_origin(tmp_path, {"ips/devices.csv": "a;b\n1;2\n"})
    with pytest.raises(DataSourceError, match="no device"):
        load_index(write_config(tmp_path, origin))


def test_config_and_git_errors_become_data_source_errors(tmp_path):
    with pytest.raises(DataSourceError, match="cannot read"):
        load_index({"MANUS_AGENT_DATA_CONFIG": str(tmp_path / "missing.yaml")})
    origin = make_origin(tmp_path)
    with pytest.raises(DataSourceError, match="does not exist"):
        load_index(write_config(tmp_path, origin, directory="nodir"))


def run_main(env):
    buffer = io.StringIO()
    with contextlib.redirect_stderr(buffer):
        code = main(env=env)
    return code, buffer.getvalue()


def agent_env(tmp_path, **extra):
    handlers = Path(__file__).resolve().parents[1] / "handlers"
    return {
        "MANUS_AGENT_ID": "ip-agent",
        "MANUS_AGENT_SECRET": SECRET,
        "MANUS_AGENT_HTTP_PORT": "8080",
        "MANUS_AGENT_HANDLERS_DIR": str(handlers),
        **extra,
    }


def test_main_exits_4_when_the_data_cannot_be_loaded(tmp_path):
    set_index(None)
    env = agent_env(tmp_path, MANUS_AGENT_DATA_CONFIG=str(tmp_path / "missing.yaml"))
    code, err = run_main(env)
    assert code == 4
    assert "cannot load the data" in err
    assert SECRET not in err


def test_main_sets_the_index_and_runs_when_the_data_loads(tmp_path):
    env = agent_env(tmp_path, **write_config(tmp_path, make_origin(tmp_path)))
    with patch("manus_agent.main._run") as run:
        code, _ = run_main(env)
    assert code == 0
    run.assert_called_once()
    assert get_index().lookup("device-1") is not None
    set_index(None)
