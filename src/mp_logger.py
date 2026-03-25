"""
Centralized logging framework for MoneyPrinter.

Replaces ad-hoc print() calls with Python's standard logging module.
Provides a project-wide logger with both console and file output,
structured formatting, and configurable log levels.

Usage:
    from mp_logger import get_logger
    logger = get_logger(__name__)
    logger.info("Video generated successfully")
    logger.warning("Retrying image generation...")
    logger.error("Upload failed", exc_info=True)
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ROOT_DIR = os.path.dirname(sys.path[0])
_LOG_DIR = os.path.join(_ROOT_DIR, ".mp", "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "moneyprinter.log")
_MAX_LOG_SIZE = 5 * 1024 * 1024  # 5 MB
_BACKUP_COUNT = 3
_DEFAULT_LEVEL = logging.INFO

# ANSI color codes for console output
_COLORS = {
    "DEBUG": "\033[36m",     # Cyan
    "INFO": "\033[32m",      # Green
    "WARNING": "\033[33m",   # Yellow
    "ERROR": "\033[31m",     # Red
    "CRITICAL": "\033[35m",  # Magenta
    "RESET": "\033[0m",
}

# ---------------------------------------------------------------------------
# Custom formatter with colors for console
# ---------------------------------------------------------------------------


class ColoredFormatter(logging.Formatter):
    """Adds ANSI color codes to log level names for terminal output."""

    def format(self, record: logging.LogRecord) -> str:
        levelname = record.levelname
        color = _COLORS.get(levelname, _COLORS["RESET"])
        record.levelname = f"{color}{levelname}{_COLORS['RESET']}"
        return super().format(record)


# ---------------------------------------------------------------------------
# Logger setup
# ---------------------------------------------------------------------------

_initialized = False


def _ensure_log_dir() -> None:
    """Creates the log directory if it doesn't exist."""
    os.makedirs(_LOG_DIR, exist_ok=True)


def _setup_root_logger() -> None:
    """
    Configures the root 'moneyprinter' logger with:
    - A colored console handler (stderr)
    - A rotating file handler (~/.mp/logs/moneyprinter.log)
    """
    global _initialized
    if _initialized:
        return

    _ensure_log_dir()

    root_logger = logging.getLogger("moneyprinter")
    root_logger.setLevel(_DEFAULT_LEVEL)
    root_logger.propagate = False

    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(_DEFAULT_LEVEL)
    console_fmt = ColoredFormatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    console_handler.setFormatter(console_fmt)
    root_logger.addHandler(console_handler)

    # File handler with rotation (plain text, no colors)
    try:
        file_handler = RotatingFileHandler(
            _LOG_FILE,
            maxBytes=_MAX_LOG_SIZE,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)  # Capture everything to file
        file_fmt = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_fmt)
        root_logger.addHandler(file_handler)
    except (OSError, PermissionError) as exc:
        # If we can't write to log file, continue with console only
        root_logger.warning(f"Could not set up file logging: {type(exc).__name__}")

    _initialized = True


def get_logger(name: str = "moneyprinter") -> logging.Logger:
    """
    Returns a logger instance under the 'moneyprinter' namespace.

    Args:
        name: Module name (typically __name__). Will be prefixed with
              'moneyprinter.' if not already.

    Returns:
        A configured logging.Logger instance.
    """
    _setup_root_logger()

    if name == "moneyprinter" or name.startswith("moneyprinter."):
        return logging.getLogger(name)

    return logging.getLogger(f"moneyprinter.{name}")


def set_log_level(level: int | str) -> None:
    """
    Updates the log level for all MoneyPrinter loggers.

    Args:
        level: A logging level (e.g. logging.DEBUG, "DEBUG", logging.WARNING).
    """
    _setup_root_logger()
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)
    root_logger = logging.getLogger("moneyprinter")
    root_logger.setLevel(level)
    for handler in root_logger.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, RotatingFileHandler
        ):
            handler.setLevel(level)
