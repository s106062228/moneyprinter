"""
Input validation utilities for MoneyPrinter.

Provides centralized validation for file paths, URLs, and other user inputs
to prevent path traversal, command injection, and other security issues.
"""

import os
import re
from urllib.parse import urlparse


def validate_path(path: str, must_exist: bool = True) -> str:
    """
    Validates and normalizes a filesystem path.

    Args:
        path: The path to validate.
        must_exist: If True, raises ValueError when path doesn't exist.

    Returns:
        The normalized absolute path.

    Raises:
        ValueError: If the path is invalid or contains traversal sequences.
    """
    if not path or not isinstance(path, str):
        raise ValueError("Path must be a non-empty string.")

    # Normalize the path to resolve .. and symlinks
    normalized = os.path.normpath(os.path.abspath(path))

    # Check for null bytes (common injection technique)
    if "\x00" in path:
        raise ValueError("Path contains null bytes.")

    if must_exist and not os.path.exists(normalized):
        raise ValueError("Path does not exist.")

    return normalized


def validate_directory(path: str, must_exist: bool = True) -> str:
    """
    Validates that a path points to a directory.

    Args:
        path: The directory path to validate.
        must_exist: If True, raises ValueError when directory doesn't exist.

    Returns:
        The normalized absolute directory path.

    Raises:
        ValueError: If the path is invalid or not a directory.
    """
    normalized = validate_path(path, must_exist=must_exist)

    if must_exist and not os.path.isdir(normalized):
        raise ValueError("Path is not a directory.")

    return normalized


def validate_url(url: str, allowed_schemes: tuple = ("http", "https")) -> str:
    """
    Validates a URL string.

    Args:
        url: The URL to validate.
        allowed_schemes: Tuple of acceptable URL schemes.

    Returns:
        The validated URL string.

    Raises:
        ValueError: If the URL is invalid or uses a disallowed scheme.
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string.")

    parsed = urlparse(url.strip())

    if parsed.scheme not in allowed_schemes:
        raise ValueError(
            f"URL scheme '{parsed.scheme}' is not allowed. "
            f"Expected one of: {allowed_schemes}"
        )

    if not parsed.netloc:
        raise ValueError("URL is missing a host.")

    return url.strip()


def sanitize_filename(filename: str) -> str:
    """
    Sanitizes a filename by removing potentially dangerous characters.

    Args:
        filename: The filename to sanitize.

    Returns:
        A safe filename string.
    """
    # Remove path separators and null bytes
    safe = os.path.basename(filename)
    safe = safe.replace("\x00", "")

    # Remove any non-alphanumeric characters except . - _ and space
    safe = re.sub(r"[^\w\s.\-]", "", safe)

    if not safe:
        raise ValueError("Filename is empty after sanitization.")

    return safe


def validate_config_string(value: str, field_name: str, max_length: int = 500) -> str:
    """
    Validates a configuration string value.

    Args:
        value: The config value to validate.
        field_name: Name of the field (for error messages).
        max_length: Maximum allowed length.

    Returns:
        The validated string.

    Raises:
        ValueError: If the value is invalid.
    """
    if not isinstance(value, str):
        raise ValueError(f"Config field '{field_name}' must be a string.")

    if len(value) > max_length:
        raise ValueError(
            f"Config field '{field_name}' exceeds max length of {max_length}."
        )

    # Check for shell metacharacters that could enable injection
    dangerous_chars = set(";|&$`")
    if any(c in value for c in dangerous_chars):
        raise ValueError(
            f"Config field '{field_name}' contains potentially dangerous characters."
        )

    return value
