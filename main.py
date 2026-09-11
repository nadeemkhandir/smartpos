"""
SmartPOS entry point.

Builds the Qt application, then hands control to :class:`AuthController`, which
decides whether this terminal goes straight to the dashboard on a remembered
session or has to ask for a password first.
"""

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from app.core.config import settings
from app.core.exceptions import DatabaseError
from app.core.logger import configure_logging, get_logger
from app.ui.auth_controller import AuthController


def main() -> int:
    configure_logging()
    logger = get_logger(__name__)

    app = QApplication(sys.argv)
    app.setApplicationName(settings.app_name)
    app.setApplicationVersion(settings.app_version)
    app.setOrganizationName(settings.organisation)

    logger.info("Starting %s %s", settings.app_name, settings.app_version)

    controller = AuthController()

    try:
        controller.start()
    except DatabaseError as error:
        # Without a database there is no sign-in and nothing to show, so say
        # what went wrong plainly and stop rather than opening a broken window.
        logger.critical("Start-up failed: %s", error)
        QMessageBox.critical(None, f"{settings.app_name} could not start", str(error))
        return 1

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
