"""pyATS job file invoked by the shim's JobRunner.

Reads the request/result file paths the shim passed via environment
variables and forwards them into the generic AEtest script as run()
parameters -- this is how one fixed job file serves every shim request
without generating a bespoke job file per call. Verified against a real
pyATS 26.7 install: custom run() kwargs are matched by name into
CommonSetup/Testcase method arguments.
"""

from __future__ import annotations

import os
from pathlib import Path

from pyats.easypy import run

_SCRIPT = Path(__file__).parent / "generic_script.py"


def main(runtime):
    request_file = os.environ["PYATS_SHIM_REQUEST_FILE"]
    result_file = os.environ["PYATS_SHIM_RESULT_FILE"]
    run(
        testscript=str(_SCRIPT),
        runtime=runtime,
        request_file=request_file,
        result_file=result_file,
    )
