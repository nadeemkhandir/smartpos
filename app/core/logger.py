"""
Application logging.

One rotating file under ``logs/`` plus console output, configured once. Modules
ask for ``get_logger(__name__)`` and never touch handlers themselves, so a
single call to :func:`configure_logging` from ``main.py`` controls the whole
application.

Secrets must never reach these files: log that a passcode was sent, never the
passcode itself.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from app.core.config import LOG_DIR

LOG_FILE = LOG_DIR / "smartpos.log"

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-28s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    """Attach the file and console handlers. Repeat calls are ignored."""
    global _configured
    if _configured:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root = logging.getLogger("smartpos")
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    root.propagate = False

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """A logger under the ``smartpos`` tree, configuring it on first use."""
    configure_logging()

    suffix = name.split(".")[-1] if name else "app"
    return logging.getLogger(f"smartpos.{suffix}")
