import sys
from os import environ
from pathlib import Path

# Expose the repo root so that plugin packages (plugins/*/backend/) are importable.
sys.path.insert(0, str(Path(__file__).parent.parent))

import uvicorn  # noqa: E402

if __name__ == "__main__":
    is_development = environ.get("ENV", "development") == "development"

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=is_development,
    )
