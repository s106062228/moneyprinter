"""
Tests for src/config.py — configuration management.
"""

import os
import json
import pytest
from unittest.mock import patch

import config as config_module


@pytest.fixture(autouse=True)
def reset_config_cache():
    """Reset the config cache before each test."""
    config_module._config_cache = None
    yield
    config_module._config_cache = None


@pytest.fixture
def mock_config(tmp_path):
    """Creates a temp config.json and patches config._config_path to use it."""
    cfg = {
        "verbose": True,
        "headless": True,
        "firefox_profile": "/tmp/test-profile",
        "ollama_model": "llama3.2:3b",
        "ollama_base_url": "http://127.0.0.1:11434",
        "nanobanana2_api_key": "test-gemini-key",
        "nanobanana2_model": "gemini-test",
        "nanobanana2_aspect_ratio": "16:9",
        "threads": 8,
        "zip_url": "https://example.com/songs.zip",
        "is_for_kids": True,
        "twitter_language": "ja",
        "tts_voice": "Nova",
        "stt_provider": "assemblyai",
        "assembly_ai_api_key": "test-aai-key",
        "whisper_model": "large-v2",
        "whisper_device": "cuda",
        "whisper_compute_type": "float16",
        "font": "Arial",
        "imagemagick_path": "/usr/local/bin/magick",
        "script_sentence_length": 6,
        "scraper_timeout": 600,
        "email": {
            "username": "user@test.com",
            "password": "secret123"
        }
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(cfg, indent=2))

    original_path = config_module._config_path
    config_module._config_path = str(config_path)
    yield cfg
    config_module._config_path = original_path


class TestConfigLoading:
    """Tests for config loading and caching."""

    def test_load_config_caches(self, mock_config):
        """Verifies config is loaded and cached in memory."""
        result1 = config_module._load_config()
        result2 = config_module._load_config()
        assert result1 is result2  # Same object (cached)

    def test_reload_config_refreshes(self, mock_config):
        """Verifies reload_config() clears cache and re-reads."""
        result1 = config_module._load_config()
        result2 = config_module.reload_config()
        assert result1 is not result2  # Different objects
        assert result1 == result2  # Same content

    def test_missing_config_returns_empty(self, tmp_path):
        """Returns empty dict when config file doesn't exist."""
        config_module._config_path = str(tmp_path / "nonexistent.json")
        result = config_module._load_config()
        assert result == {}

    def test_invalid_json_returns_empty(self, tmp_path):
        """Returns empty dict when config file has invalid JSON."""
        bad_config = tmp_path / "bad.json"
        bad_config.write_text("not valid json {{{")
        config_module._config_path = str(bad_config)
        result = config_module._load_config()
        assert result == {}


class TestConfigGetters:
    """Tests for individual config getter functions."""

    def test_get_verbose(self, mock_config):
        assert config_module.get_verbose() is True

    def test_get_headless(self, mock_config):
        assert config_module.get_headless() is True

    def test_get_firefox_profile_path(self, mock_config):
        assert config_module.get_firefox_profile_path() == "/tmp/test-profile"

    def test_get_ollama_model(self, mock_config):
        assert config_module.get_ollama_model() == "llama3.2:3b"

    def test_get_ollama_base_url(self, mock_config):
        assert config_module.get_ollama_base_url() == "http://127.0.0.1:11434"

    def test_get_threads(self, mock_config):
        assert config_module.get_threads() == 8

    def test_get_is_for_kids(self, mock_config):
        assert config_module.get_is_for_kids() is True

    def test_get_twitter_language(self, mock_config):
        assert config_module.get_twitter_language() == "ja"

    def test_get_tts_voice(self, mock_config):
        assert config_module.get_tts_voice() == "Nova"

    def test_get_stt_provider(self, mock_config):
        assert config_module.get_stt_provider() == "assemblyai"

    def test_get_whisper_model(self, mock_config):
        assert config_module.get_whisper_model() == "large-v2"

    def test_get_whisper_device(self, mock_config):
        assert config_module.get_whisper_device() == "cuda"

    def test_get_whisper_compute_type(self, mock_config):
        assert config_module.get_whisper_compute_type() == "float16"

    def test_get_font(self, mock_config):
        assert config_module.get_font() == "Arial"

    def test_get_imagemagick_path(self, mock_config):
        assert config_module.get_imagemagick_path() == "/usr/local/bin/magick"

    def test_get_script_sentence_length(self, mock_config):
        assert config_module.get_script_sentence_length() == 6

    def test_get_scraper_timeout(self, mock_config):
        assert config_module.get_scraper_timeout() == 600

    def test_get_zip_url(self, mock_config):
        assert config_module.get_zip_url() == "https://example.com/songs.zip"

    def test_get_nanobanana2_api_key(self, mock_config):
        assert config_module.get_nanobanana2_api_key() == "test-gemini-key"

    def test_get_nanobanana2_model(self, mock_config):
        assert config_module.get_nanobanana2_model() == "gemini-test"

    def test_get_nanobanana2_aspect_ratio(self, mock_config):
        assert config_module.get_nanobanana2_aspect_ratio() == "16:9"


class TestConfigDefaults:
    """Tests that defaults are returned when keys are missing."""

    def test_default_verbose(self, tmp_path):
        """Defaults to False when verbose is not in config."""
        config_path = tmp_path / "empty.json"
        config_path.write_text("{}")
        config_module._config_path = str(config_path)
        assert config_module.get_verbose() is False

    def test_default_ollama_base_url(self, tmp_path):
        config_path = tmp_path / "empty.json"
        config_path.write_text("{}")
        config_module._config_path = str(config_path)
        assert config_module.get_ollama_base_url() == "http://127.0.0.1:11434"

    def test_default_threads(self, tmp_path):
        config_path = tmp_path / "empty.json"
        config_path.write_text("{}")
        config_module._config_path = str(config_path)
        assert config_module.get_threads() == 2

    def test_default_whisper_model(self, tmp_path):
        config_path = tmp_path / "empty.json"
        config_path.write_text("{}")
        config_module._config_path = str(config_path)
        assert config_module.get_whisper_model() == "base"

    def test_default_script_sentence_length(self, tmp_path):
        config_path = tmp_path / "empty.json"
        config_path.write_text("{}")
        config_module._config_path = str(config_path)
        assert config_module.get_script_sentence_length() == 4


class TestEnvVarFallbacks:
    """Tests for environment variable fallbacks."""

    def test_gemini_api_key_env_fallback(self, tmp_path):
        """Falls back to GEMINI_API_KEY env var when config key is empty."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"nanobanana2_api_key": ""}))
        config_module._config_path = str(config_path)

        with patch.dict(os.environ, {"GEMINI_API_KEY": "env-gemini-key"}):
            assert config_module.get_nanobanana2_api_key() == "env-gemini-key"

    def test_assemblyai_key_env_fallback(self, tmp_path):
        """Falls back to ASSEMBLYAI_API_KEY env var when config key is empty."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"assembly_ai_api_key": ""}))
        config_module._config_path = str(config_path)

        with patch.dict(os.environ, {"ASSEMBLYAI_API_KEY": "env-aai-key"}):
            assert config_module.get_assemblyai_api_key() == "env-aai-key"

    def test_email_env_fallback(self, tmp_path):
        """Falls back to MP_EMAIL_* env vars when config email is empty."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"email": {}}))
        config_module._config_path = str(config_path)

        with patch.dict(os.environ, {
            "MP_EMAIL_USERNAME": "env@test.com",
            "MP_EMAIL_PASSWORD": "env-pass",
        }):
            creds = config_module.get_email_credentials()
            assert creds["username"] == "env@test.com"
            assert creds["password"] == "env-pass"

    def test_config_value_takes_precedence_over_env(self, mock_config):
        """Config file values take precedence over env vars."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "should-not-use"}):
            assert config_module.get_nanobanana2_api_key() == "test-gemini-key"


class TestGetPipelineHealthAutoSaveInterval:
    """Tests for get_pipeline_health_auto_save_interval()."""

    def test_returns_configured_value(self, tmp_path):
        """Returns the value set in config.json."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"pipeline_health_auto_save_interval": 25}))
        config_module._config_path = str(config_path)
        assert config_module.get_pipeline_health_auto_save_interval() == 25

    def test_returns_default_10_when_key_missing(self, tmp_path):
        """Returns default of 10 when key is absent."""
        config_path = tmp_path / "config.json"
        config_path.write_text("{}")
        config_module._config_path = str(config_path)
        assert config_module.get_pipeline_health_auto_save_interval() == 10

    def test_clamps_to_min_1(self, tmp_path):
        """Values <= 0 are clamped to 1."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"pipeline_health_auto_save_interval": 0}))
        config_module._config_path = str(config_path)
        assert config_module.get_pipeline_health_auto_save_interval() == 1

    def test_clamps_negative_to_min_1(self, tmp_path):
        """Negative values are clamped to 1."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"pipeline_health_auto_save_interval": -50}))
        config_module._config_path = str(config_path)
        assert config_module.get_pipeline_health_auto_save_interval() == 1

    def test_clamps_to_max_10000(self, tmp_path):
        """Values > 10000 are clamped to 10000."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"pipeline_health_auto_save_interval": 99999}))
        config_module._config_path = str(config_path)
        assert config_module.get_pipeline_health_auto_save_interval() == 10000

    def test_invalid_string_returns_default_10(self, tmp_path):
        """Non-numeric string falls back to default 10."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"pipeline_health_auto_save_interval": "not-a-number"}))
        config_module._config_path = str(config_path)
        assert config_module.get_pipeline_health_auto_save_interval() == 10

    def test_none_value_returns_default_10(self, tmp_path):
        """None value falls back to default 10."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"pipeline_health_auto_save_interval": None}))
        config_module._config_path = str(config_path)
        assert config_module.get_pipeline_health_auto_save_interval() == 10
