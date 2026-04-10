"""
Tests for src/llm_provider.py — Ollama LLM integration.

These tests focus on the model selection logic without requiring
a running Ollama server. The ollama module is mocked at import time.
"""

import sys
import pytest
from unittest.mock import patch, MagicMock

# Mock the ollama module before importing llm_provider
mock_ollama = MagicMock()
sys.modules["ollama"] = mock_ollama

import llm_provider


@pytest.fixture(autouse=True)
def reset_model():
    """Reset the selected model before each test."""
    llm_provider._selected_model = None
    yield
    llm_provider._selected_model = None


class TestSelectModel:
    """Tests for model selection."""

    def test_select_model(self):
        """Sets the model name."""
        llm_provider.select_model("llama3.2:3b")
        assert llm_provider.get_active_model() == "llama3.2:3b"

    def test_get_active_model_default(self):
        """Returns None when no model selected."""
        assert llm_provider.get_active_model() is None

    def test_select_model_overwrite(self):
        """Selecting again overwrites the previous model."""
        llm_provider.select_model("model-a")
        llm_provider.select_model("model-b")
        assert llm_provider.get_active_model() == "model-b"


class TestGenerateText:
    """Tests for generate_text()."""

    def test_no_model_raises(self):
        """Raises RuntimeError when no model is selected."""
        with pytest.raises(RuntimeError, match="No Ollama model selected"):
            llm_provider.generate_text("Hello")

    @patch.object(llm_provider, "_client")
    def test_generate_with_selected_model(self, mock_client_fn):
        """Uses the selected model when no override provided."""
        mock_client = MagicMock()
        mock_client.chat.return_value = {"message": {"content": "Generated response"}}
        mock_client_fn.return_value = mock_client

        llm_provider.select_model("test-model")
        result = llm_provider.generate_text("Hello")

        assert result == "Generated response"
        mock_client.chat.assert_called_once_with(
            model="test-model",
            messages=[{"role": "user", "content": "Hello"}],
        )

    @patch.object(llm_provider, "_client")
    def test_generate_with_override_model(self, mock_client_fn):
        """Uses the override model when provided."""
        mock_client = MagicMock()
        mock_client.chat.return_value = {"message": {"content": "Response"}}
        mock_client_fn.return_value = mock_client

        llm_provider.select_model("default-model")
        result = llm_provider.generate_text("Hello", model_name="override-model")

        assert result == "Response"
        mock_client.chat.assert_called_once_with(
            model="override-model",
            messages=[{"role": "user", "content": "Hello"}],
        )

    @patch.object(llm_provider, "_client")
    def test_generate_strips_whitespace(self, mock_client_fn):
        """Output is stripped of leading/trailing whitespace."""
        mock_client = MagicMock()
        mock_client.chat.return_value = {"message": {"content": "  padded output  "}}
        mock_client_fn.return_value = mock_client

        llm_provider.select_model("test-model")
        result = llm_provider.generate_text("Hello")
        assert result == "padded output"
