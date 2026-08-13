"""Marker string for pyATS per-device connect log lines.

Kept in its own module with no other imports so ``job_runner.py`` (which
runs in the shim process itself) can filter subprocess output for it without
importing ``app.job_scripts.generic_script``, which does ``from pyats import
aetest`` -- that import must only ever happen inside the per-request pyATS
subprocess, not the shim process, per doc/PYATS_INTEGRATION.md ("tests/ ...
mocks the subprocess -- no pyATS install needed").
"""

from __future__ import annotations

CONNECT_MARKER = "[pyats-connect]"
