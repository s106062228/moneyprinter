"""
Tests for src/llm_provider.py — Multi-LLM provider system.

Tests cover:
  - Provider creation and registration
  - Model selection (backward-compatible API)
  - generate_text() routing
  - Provider switching
  - Error handling (missing keys, unknown providers)
  - Each provider class in isolation
"""

import sys
import pytest
from unittest.mock import patch, MagicMock

# Mock external provider SDKs before importing llm_provider
mock_ollama = MagicMock()
sys.modules["ollama"] = mock_ollama
sys.modules["openai"] = MagicMock()
sys.modules["anthropic"] = MagicMock()
sys.modules["groq"] = MagicMock()

import llm_provider


@pytest.fixture(autouse=True)
def reset_state():
    """Reset the module-level state before each test."""
    llm_provider._selected_model = None
    llm_provider._active_provider = None
    yield
    llm_provider._selected_model = None
    llm_provider._active_provider = None


# ---------------------------------------------------------------------------
# Provider registry tests
# ---------------------------------------------------------------------------

class TestProviderRegistry:
    """Tests for provider registration and creation."""

    def test_get_available_providers(self):
        """Returns all registered provider names."""
        providers = llm_provider.get_available_providers()
        assert "ollama" in providers
        assert "openai" in providers
        assert "anthropic" in providers
        assert "groq" in providers

    def test_create_provider_unknown_raises(self):
        """Raises ValueError for unknown provider names."""
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            llm_provider.create_provider("nonexistent")

    @patch("llm_provider.get_llm_provider", return_value="ollama")
    @patch("llm_provider.get_ollama_base_url", return_value="http://127.0.0.1:11434")
    def test_create_ollama_provider(self, mock_url, mock_prov):
        """Creates an OllamaProvider successfully."""
        provider = llm_provider.create_provider("ollama")
        assert isinstance(provider, llm_provider.OllamaProvider)
        assert provider.name == "ollama"

    @patch("llm_provider.get_openai_api_key", return_value="sk-test-key")
    @patch("llm_provider.get_openai_model", return_value="gpt-4o-mini")
    def test_create_openai_provider(self, mock_model, mock_key):
        """Creates an OpenAIProvider successfully."""
        provider = llm_provider.create_provider("openai")
        assert isinstance(provider, llm_provider.OpenAIProvider)
        assert provider.name == "openai"

    @patch("llm_provider.get_openai_api_key", return_value="")
    def test_create_openai_no_key_raises(self, mock_key):
        """Raises ValueError when OpenAI key is missing."""
        with pytest.raises(ValueError, match="OpenAI API key not configured"):
            llm_provider.create_provider("openai")

    @patch("llm_provider.get_anthropic_api_key", return_value="sk-ant-test")
    @patch("llm_provider.get_anthropic_model", return_value="claude-sonnet-4-6")
    def test_create_anthropic_provider(self, mock_model, mock_key):
        """Creates an AnthropicProvider successfully."""
        provider = llm_provider.create_provider("anthropic")
        assert isinstance(provider, llm_provider.AnthropicProvider)
        assert provider.name == "anthropic"

    @patch("llm_provider.get_anthropic_api_key", return_value="")
    def test_create_anthropic_no_key_raises(self, mock_key):
        """Raises ValueError when Anthropic key is missing."""
        with pytest.raises(ValueError, match="Anthropic API key not configured"):
            llm_provider.create_provider("anthropic")

    @patch("llm_provider.get_groq_api_key", return_value="gsk_test")
    @patch("llm_provider.get_groq_model", return_value="llama-3.3-70b-versatile")
    def test_create_groq_provider(self, mock_model, mock_key):
        """Creates a GroqProvider successfully."""
        provider = llm_provider.create_provider("groq")
        assert isinstance(provider, llm_provider.GroqProvider)
        assert provider.name == "groq"

    @patch("llm_provider.get_groq_api_key", return_value="")
    def test_create_groq_no_key_raises(self, mock_key):
        """Raises ValueError when Groq key is missing."""
        with pytest.raises(ValueError, match="Groq API key not configured"):
            llm_provider.create_provider("groq")


# ---------------------------------------------------------------------------
# Backward-compatible API tests
# ---------------------------------------------------------------------------

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
        with pytest.raises(RuntimeError, match="No model selected"):
            llm_provider.generate_text("Hello")

    @patch("llm_provider.get_llm_provider", return_value="ollama")
    @patch("llm_provider.get_ollama_base_url", return_value="http://127.0.0.1:11434")
    def test_generate_with_ollama(self, mock_url, mock_prov):
        """Generates text through the Ollama provider."""
        mock_client = MagicMock()
        mock_client.chat.return_value = {"message": {"content": "Hello world"}}
        mock_ollama.Client.return_value = mock_client

        llm_provider.set_provider("ollama")
        llm_provider.select_model("test-model")
        result = llm_provider.generate_text("Hello")

        assert result == "Hello world"
        mock_client.chat.assert_called_once_with(
            model="test-model",
            messages=[{"role": "user", "content": "Hello"}],
        )

    @patch("llm_provider.get_llm_provider", return_value="ollama")
    @patch("llm_provider.get_ollama_base_url", return_value="http://127.0.0.1:11434")
    def test_generate_strips_whitespace(self, mock_url, mock_prov):
        """Output is stripped of leading/trailing whitespace."""
        mock_client = MagicMock()
        mock_client.chat.return_value = {"message": {"content": "  padded output  "}}
        mock_ollama.Client.return_value = mock_client

        llm_provider.set_provider("ollama")
        llm_provider.select_model("test-model")
        result = llm_provider.generate_text("Hello")
        assert result == "padded output"

    @patch("llm_provider.get_llm_provider", return_value="ollama")
    @patch("llm_provider.get_ollama_base_url", return_value="http://127.0.0.1:11434")
    def test_generate_with_override_model(self, mock_url, mock_prov):
        """Uses the override model when provided."""
        mock_client = MagicMock()
        mock_client.chat.return_value = {"message": {"content": "Response"}}
        mock_ollama.Client.return_value = mock_client

        llm_provider.set_provider("ollama")
        llm_provider.select_model("default-model")
        result = llm_provider.generate_text("Hello", model_name="override-model")

        assert result == "Response"
        mock_client.chat.assert_called_once_with(
            model="override-model",
            messages=[{"role": "user", "content": "Hello"}],
        )


# ---------------------------------------------------------------------------
# Provider switching tests
# ---------------------------------------------------------------------------

class TestProviderSwitching:
    """Tests for switching providers at runtime."""

    @patch("llm_provider.get_llm_provider", return_value="ollama")
    @patch("llm_provider.get_ollama_base_url", return_value="http://127.0.0.1:11434")
    def test_set_provider(self, mock_url, mock_prov):
        """set_provider() switches the active provider."""
        llm_provider.set_provider("ollama")
        assert llm_provider.get_provider_name() == "ollama"

    @patch("llm_provider.get_openai_api_key", return_value="sk-test")
    @patch("llm_provider.get_openai_model", return_value="gpt-4o-mini")
    def test_switch_to_openai(self, mock_model, mock_key):
        """Can switch from default to OpenAI."""
        llm_provider.set_provider("openai")
        assert llm_provider.get_provider_name() == "openai"

    def test_set_provider_invalid_raises(self):
        """Raises ValueError for invalid provider."""
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            llm_provider.set_provider("invalid_provider")


# ---------------------------------------------------------------------------
# Provider list_models tests
# ---------------------------------------------------------------------------

class TestListModels:
    """Tests for list_models across providers."""

    @patch("llm_provider.get_openai_api_key", return_value="sk-test")
    @patch("llm_provider.get_openai_model", return_value="gpt-4o-mini")
    def test_openai_list_models(self, mock_model, mock_key):
        """OpenAI provider returns known models."""
        provider = llm_provider.OpenAIProvider()
        models = provider.list_models()
        assert "gpt-4o" in models
        assert "gpt-4o-mini" in models

    @patch("llm_provider.get_anthropic_api_key", return_value="sk-ant-test")
    @patch("llm_provider.get_anthropic_model", return_value="claude-sonnet-4-6")
    def test_anthropic_list_models(self, mock_model, mock_key):
        """Anthropic provider returns known models."""
        provider = llm_provider.AnthropicProvider()
        models = provider.list_models()
        assert "claude-sonnet-4-6" in models

    @patch("llm_provider.get_groq_api_key", return_value="gsk_test")
    @patch("llm_provider.get_groq_model", return_value="llama-3.3-70b-versatile")
    def test_groq_list_models(self, mock_model, mock_key):
        """Groq provider returns known models."""
        provider = llm_provider.GroqProvider()
        models = provider.list_models()
        assert "llama-3.3-70b-versatile" in models

    @patch("llm_provider.get_llm_provider", return_value="ollama")
    @patch("llm_provider.get_ollama_base_url", return_value="http://127.0.0.1:11434")
    def test_ollama_list_models(self, mock_url, mock_prov):
        """Ollama provider lists models from server."""
        mock_model = MagicMock()
        mock_model.model = "llama3.2:3b"
        mock_response = MagicMock()
        mock_response.models = [mock_model]
        mock_ollama.Client.return_value.list.return_value = mock_response

        provider = llm_provider.OllamaProvider()
        models = provider.list_models()
        assert "llama3.2:3b" in models


# ---------------------------------------------------------------------------
# Ollama provider no-model error test
# ---------------------------------------------------------------------------

class TestOllamaNoModel:
    """Test Ollama-specific error handling."""

    @patch("llm_provider.get_ollama_base_url", return_value="http://127.0.0.1:11434")
    def test_generate_no_model_raises(self, mock_url):
        """Ollama provider raises when no model specified."""
        provider = llm_provider.OllamaProvider()
        with pytest.raises(RuntimeError, match="No model specified"):
            provider.generate("Hello")
