import os
from pathlib import Path

# The list_devices handler reads its config.yaml when the handlers are loaded; every test that loads
# the handlers directory gets this one unless it sets MANUS_AGENT_CONFIG itself.
os.environ.setdefault(
    "MANUS_AGENT_CONFIG", str(Path(__file__).resolve().parent / "fixtures" / "test-config.yaml")
)
