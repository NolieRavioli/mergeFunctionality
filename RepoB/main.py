# main.py

import logging

from db.database import initialize_public_database
from util.utils import ensure_dependencies, initialize_runtime_environment
from webUI.app import start_webUI

logger = logging.getLogger(__name__)


def main() -> None:
    """Entry point that prepares runtime, validates deps, then launches Flask."""

    settings = initialize_runtime_environment()
    ensure_dependencies(settings)

    logger.info("Initializing databases...")
    initialize_public_database()

    logger.info("Starting EVE Data Framework WebUI...")
    start_webUI(settings)


if __name__ == "__main__":
    main()
