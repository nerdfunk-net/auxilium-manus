#!/usr/bin/env python3
"""
Cockpit Backend Startup Script
Loads configuration and starts the FastAPI server.
"""

import logging
import os

import uvicorn

from cert_installer import install_certificates
from config import settings
from services.settings.manager import SettingsManager as _SM

settings_manager = _SM()


def initialize_database_settings():
    """Initialize database settings with environment variables if empty"""
    try:
        # Check if we have valid database settings
        db_settings = settings_manager.get_nautobot_settings()

        # If no valid token in database, initialize with environment settings
        if (
            not db_settings
            or not db_settings.get("token")
            or db_settings.get("token") == ""
        ):
            logger.info("Initializing database with environment variable settings")
            nautobot_settings = {
                "url": settings.nautobot_url,
                "token": settings.nautobot_token,
                "timeout": settings.nautobot_timeout,
                "verify_ssl": True,
            }

            success = settings_manager.update_nautobot_settings(nautobot_settings)
            if success:
                logger.info("Database settings initialized successfully")
            else:
                logger.warning("Failed to initialize database settings")
        else:
            logger.info("Using existing database settings")

    except Exception as e:
        logger.error("Error initializing database settings: %s", e)


def main():
    """Start the FastAPI server with configuration."""

    # Install certificates before anything else (Docker environments)
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    install_certificates(backend_dir)

    # Configure logging
    # Ensure log_level is valid, default to INFO if invalid
    try:
        log_level = getattr(logging, settings.log_level)
    except AttributeError:
        log_level = logging.INFO
        print(f"Warning: Invalid LOG_LEVEL '{settings.log_level}', defaulting to INFO")

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Suppress debug logging from GitPython
    logging.getLogger("git.cmd").setLevel(logging.WARNING)
    logging.getLogger("git.repo").setLevel(logging.WARNING)

    # Suppress debug logging from Celery
    logging.getLogger("celery").setLevel(logging.INFO)
    logging.getLogger("celery.utils.functional").setLevel(logging.INFO)

    global logger
    logger = logging.getLogger(__name__)

    # Log current log level for verification
    logger.debug("DEBUG: Logging configured at %s level", settings.log_level)
    logger.debug("DEBUG: Environment LOG_LEVEL = %s", os.getenv("LOG_LEVEL", "not set"))

    # Initialize database settings
    initialize_database_settings()

    # Log startup information
    logger.info("Starting Cockpit Backend Server")
    logger.info("Server: %s:%s", settings.host, settings.port)
    logger.info("Log Level: %s", settings.log_level)
    logger.info("Data Directory: %s", settings.data_directory)
    logger.info("Nautobot (env): %s", settings.nautobot_url)

    # Start the server
    # Get the backend directory path
    backend_dir = os.path.dirname(__file__)

    # Change to backend directory to ensure Uvicorn only watches backend files
    original_cwd = os.getcwd()
    os.chdir(backend_dir)

    try:
        uvicorn.run(
            "main:app",
            host=settings.host,
            port=settings.port,
            reload=False,
            log_level=settings.log_level.lower(),
            access_log=True,
        )
    finally:
        os.chdir(original_cwd)


if __name__ == "__main__":
    main()
