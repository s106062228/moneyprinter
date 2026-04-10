"""
Shared fixtures for MoneyPrinter test suite.
"""

import os
import sys
import json
import pytest
import tempfile
import shutil

# Add src/ to the Python path so we can import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture
def tmp_dir(tmp_path):
    """Provides a temporary directory that is cleaned up after the test."""
    return tmp_path


@pytest.fixture
def sample_config(tmp_path):
    """Creates a sample config.json and returns its path."""
    config = {
        "verbose": True,
        "headless": False,
        "firefox_profile": "/tmp/fake-profile",
        "ollama_model": "llama3.2:3b",
        "ollama_base_url": "http://127.0.0.1:11434",
        "nanobanana2_api_key": "test-key-123",
        "nanobanana2_api_base_url": "https://generativelanguage.googleapis.com/v1beta",
        "nanobanana2_model": "gemini-3.1-flash-image-preview",
        "nanobanana2_aspect_ratio": "9:16",
        "threads": 4,
        "zip_url": "",
        "is_for_kids": False,
        "twitter_language": "en",
        "tts_voice": "Jasper",
        "stt_provider": "local_whisper",
        "whisper_model": "base",
        "whisper_device": "auto",
        "whisper_compute_type": "int8",
        "font": "Lexend Bold",
        "imagemagick_path": "/usr/bin/convert",
        "script_sentence_length": 4,
        "email": {
            "username": "test@example.com",
            "password": "test-password"
        }
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config, indent=2))
    return str(config_path)


@pytest.fixture
def mp_dir(tmp_path):
    """Creates a mock .mp directory structure."""
    mp = tmp_path / ".mp"
    mp.mkdir()
    logs = mp / "logs"
    logs.mkdir()
    return str(mp)


@pytest.fixture
def analytics_file(tmp_path):
    """Creates a temporary analytics file path."""
    mp = tmp_path / ".mp"
    mp.mkdir(exist_ok=True)
    return str(mp / "analytics.json")


@pytest.fixture
def cache_dir(tmp_path):
    """Creates a temporary cache directory with empty cache files."""
    mp = tmp_path / ".mp"
    mp.mkdir(exist_ok=True)

    for name in ["twitter.json", "youtube.json", "afm.json"]:
        cache_file = mp / name
        if "afm" in name:
            cache_file.write_text(json.dumps({"products": []}, indent=4))
        else:
            cache_file.write_text(json.dumps({"accounts": []}, indent=4))

    return str(mp)
