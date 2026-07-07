import logging
import os
import sys
from pathlib import Path

# Ensure the backend directory is on sys.path so workflow_steps packages are importable.
sys.path.insert(0, str(Path(__file__).parent))

from core.config import settings  # noqa: E402 — loads .env via load_dotenv()
from core.logging_config import configure_logging  # noqa: E402

if __name__ == "__main__":
    import uvicorn

    log_config = configure_logging("app")

    logger = logging.getLogger(__name__)
    logger.debug("Log level: %s", settings.log_level)

    is_development = settings.environment == "development"

    host = os.environ.get("BACKEND_HOST", "127.0.0.1")
    port = int(os.environ.get("BACKEND_PORT", "8001"))

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=is_development,
        log_config=log_config,
        log_level=settings.log_level.lower(),
    )
