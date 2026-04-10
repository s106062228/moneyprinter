"""
Tests for src/validation.py — input validation utilities.
"""

import os
import pytest
from validation import (
    validate_path,
    validate_directory,
    validate_url,
    sanitize_filename,
    validate_config_string,
)


class TestValidatePath:
    """Tests for validate_path()."""

    def test_valid_existing_path(self, tmp_path):
        """Validates an existing file path returns normalized absolute path."""
        f = tmp_path / "test.txt"
        f.write_text("hello")
        result = validate_path(str(f), must_exist=True)
        assert os.path.isabs(result)
        assert result == str(f)

    def test_nonexistent_path_must_exist_raises(self):
        """Raises ValueError when must_exist=True and path doesn't exist."""
        with pytest.raises(ValueError, match="does not exist"):
            validate_path("/nonexistent/path/abc123", must_exist=True)

    def test_nonexistent_path_must_exist_false(self):
        """Returns normalized path when must_exist=False."""
        result = validate_path("/some/nonexistent/path", must_exist=False)
        assert os.path.isabs(result)

    def test_empty_path_raises(self):
        """Raises ValueError for empty string."""
        with pytest.raises(ValueError, match="non-empty string"):
            validate_path("", must_exist=False)

    def test_none_path_raises(self):
        """Raises ValueError for None."""
        with pytest.raises(ValueError, match="non-empty string"):
            validate_path(None, must_exist=False)

    def test_null_byte_raises(self):
        """Raises ValueError when path contains null bytes."""
        with pytest.raises(ValueError, match="null bytes"):
            validate_path("/tmp/test\x00evil", must_exist=False)

    def test_path_traversal_normalized(self, tmp_path):
        """Ensures .. sequences are resolved via normpath."""
        f = tmp_path / "subdir" / "test.txt"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("hello")
        # Use traversal path
        traversal = str(tmp_path / "subdir" / ".." / "subdir" / "test.txt")
        result = validate_path(traversal, must_exist=True)
        assert ".." not in result


class TestValidateDirectory:
    """Tests for validate_directory()."""

    def test_valid_directory(self, tmp_path):
        """Validates an existing directory."""
        result = validate_directory(str(tmp_path), must_exist=True)
        assert os.path.isdir(result)

    def test_file_not_directory_raises(self, tmp_path):
        """Raises ValueError when path points to a file, not directory."""
        f = tmp_path / "file.txt"
        f.write_text("content")
        with pytest.raises(ValueError, match="not a directory"):
            validate_directory(str(f), must_exist=True)


class TestValidateUrl:
    """Tests for validate_url()."""

    def test_valid_https_url(self):
        """Accepts a valid HTTPS URL."""
        result = validate_url("https://example.com/path")
        assert result == "https://example.com/path"

    def test_valid_http_url(self):
        """Accepts a valid HTTP URL."""
        result = validate_url("http://localhost:8080")
        assert result == "http://localhost:8080"

    def test_invalid_scheme_raises(self):
        """Raises ValueError for unsupported schemes like ftp."""
        with pytest.raises(ValueError, match="not allowed"):
            validate_url("ftp://example.com")

    def test_no_host_raises(self):
        """Raises ValueError when URL has no host."""
        with pytest.raises(ValueError, match="missing a host"):
            validate_url("https://")

    def test_empty_url_raises(self):
        """Raises ValueError for empty string."""
        with pytest.raises(ValueError, match="non-empty string"):
            validate_url("")

    def test_none_url_raises(self):
        """Raises ValueError for None."""
        with pytest.raises(ValueError, match="non-empty string"):
            validate_url(None)

    def test_strips_whitespace(self):
        """Strips leading/trailing whitespace."""
        result = validate_url("  https://example.com  ")
        assert result == "https://example.com"

    def test_custom_allowed_schemes(self):
        """Accepts custom allowed schemes."""
        result = validate_url("ftp://files.example.com", allowed_schemes=("ftp",))
        assert result == "ftp://files.example.com"


class TestSanitizeFilename:
    """Tests for sanitize_filename()."""

    def test_simple_filename(self):
        """Simple alphanumeric filename passes through."""
        assert sanitize_filename("video.mp4") == "video.mp4"

    def test_removes_path_separators(self):
        """Strips directory components."""
        assert sanitize_filename("/etc/passwd") == "passwd"
        assert sanitize_filename("../../secret.txt") == "secret.txt"

    def test_removes_dangerous_chars(self):
        """Removes shell metacharacters."""
        result = sanitize_filename("file;rm -rf.txt")
        assert ";" not in result

    def test_removes_null_bytes(self):
        """Strips null bytes from filename."""
        result = sanitize_filename("file\x00name.txt")
        assert "\x00" not in result

    def test_empty_after_sanitize_raises(self):
        """Raises ValueError when nothing remains after sanitization."""
        with pytest.raises(ValueError, match="empty after sanitization"):
            sanitize_filename(";;;")

    def test_preserves_spaces_dashes_underscores(self):
        """Preserves common safe characters."""
        result = sanitize_filename("my file-name_v2.txt")
        assert result == "my file-name_v2.txt"


class TestValidateConfigString:
    """Tests for validate_config_string()."""

    def test_valid_string(self):
        """Normal string passes validation."""
        result = validate_config_string("hello world", "test_field")
        assert result == "hello world"

    def test_exceeds_max_length_raises(self):
        """Raises ValueError when string is too long."""
        with pytest.raises(ValueError, match="exceeds max length"):
            validate_config_string("a" * 501, "test_field")

    def test_custom_max_length(self):
        """Respects custom max_length parameter."""
        with pytest.raises(ValueError, match="exceeds max length"):
            validate_config_string("abcdef", "test_field", max_length=5)

    def test_dangerous_semicolon_raises(self):
        """Raises ValueError for shell metacharacter semicolon."""
        with pytest.raises(ValueError, match="dangerous characters"):
            validate_config_string("value; rm -rf /", "test_field")

    def test_dangerous_pipe_raises(self):
        """Raises ValueError for shell metacharacter pipe."""
        with pytest.raises(ValueError, match="dangerous characters"):
            validate_config_string("value | cat /etc/passwd", "test_field")

    def test_dangerous_ampersand_raises(self):
        """Raises ValueError for shell metacharacter ampersand."""
        with pytest.raises(ValueError, match="dangerous characters"):
            validate_config_string("value & echo pwned", "test_field")

    def test_dangerous_dollar_raises(self):
        """Raises ValueError for shell metacharacter dollar sign."""
        with pytest.raises(ValueError, match="dangerous characters"):
            validate_config_string("value $HOME", "test_field")

    def test_dangerous_backtick_raises(self):
        """Raises ValueError for shell metacharacter backtick."""
        with pytest.raises(ValueError, match="dangerous characters"):
            validate_config_string("value `whoami`", "test_field")

    def test_non_string_raises(self):
        """Raises ValueError for non-string input."""
        with pytest.raises(ValueError, match="must be a string"):
            validate_config_string(123, "test_field")
