import sys
import types

from app.health import health_pyats
from tests import TEST_TOKEN


async def test_health_reports_limits(monkeypatch):
    monkeypatch.setenv("PYATS_SHIM_TOKEN", TEST_TOKEN)
    monkeypatch.setenv("PYATS_SHIM_MAX_CONCURRENT_JOBS", "7")
    monkeypatch.setenv("PYATS_SHIM_JOB_TIMEOUT_SECONDS", "90")
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setitem(sys.modules, "pyats", types.SimpleNamespace(__version__="1"))
    monkeypatch.setitem(sys.modules, "genie", types.SimpleNamespace(__version__="2"))
    try:
        body = await health_pyats()
    finally:
        get_settings.cache_clear()
    assert body["status"] == "ok"
    assert body["max_concurrent_jobs"] == 7
    assert body["job_timeout_seconds"] == 90.0
