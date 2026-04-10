"""
Tests for src/mp_logger.py — centralized logging framework.
"""

import logging
import pytest
from unittest.mock import patch

import mp_logger


@pytest.fixture(autouse=True)
def reset_logger():
    """Reset the logger initialization state before each test."""
    mp_logger._initialized = False
    # Remove existing handlers from the moneyprinter logger
    root = logging.getLogger("moneyprinter")
    root.handlers.clear()
    yield
    mp_logger._initialized = False
    root.handlers.clear()


class TestGetLogger:
    """Tests for get_logger()."""

    def test_returns_logger_instance(self):
        """Returns a logging.Logger instance."""
        logger = mp_logger.get_logger("test_module")
        assert isinstance(logger, logging.Logger)

    def test_logger_name_prefixed(self):
        """Logger name is prefixed with 'moneyprinter.'."""
        logger = mp_logger.get_logger("mymodule")
        assert logger.name == "moneyprinter.mymodule"

    def test_root_logger_name(self):
        """Passing 'moneyprinter' returns root moneyprinter logger."""
        logger = mp_logger.get_logger("moneyprinter")
        assert logger.name == "moneyprinter"

    def test_already_prefixed_name(self):
        """Name starting with 'moneyprinter.' is not double-prefixed."""
        logger = mp_logger.get_logger("moneyprinter.submodule")
        assert logger.name == "moneyprinter.submodule"

    def test_logger_can_log(self, capfd):
        """Logger produces output."""
        logger = mp_logger.get_logger("test_output")
        logger.info("Test message")
        captured = capfd.readouterr()
        # Output goes to stderr
        assert "Test message" in captured.err


class TestSetLogLevel:
    """Tests for set_log_level()."""

    def test_set_level_by_int(self):
        """Sets log level using integer constant."""
        mp_logger.set_log_level(logging.DEBUG)
        root = logging.getLogger("moneyprinter")
        assert root.level == logging.DEBUG

    def test_set_level_by_string(self):
        """Sets log level using string name."""
        mp_logger.set_log_level("WARNING")
        root = logging.getLogger("moneyprinter")
        assert root.level == logging.WARNING

    def test_set_level_case_insensitive(self):
        """String level names are case-insensitive."""
        mp_logger.set_log_level("debug")
        root = logging.getLogger("moneyprinter")
        assert root.level == logging.DEBUG


class TestColoredFormatter:
    """Tests for ColoredFormatter."""

    def test_format_adds_color(self):
        """Formatter adds ANSI color codes to level name."""
        formatter = mp_logger.ColoredFormatter(fmt="%(levelname)s: %(message)s")
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        formatted = formatter.format(record)
        assert "\033[32m" in formatted  # Green for INFO
        assert "hello" in formatted
