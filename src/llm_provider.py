"""
Multi-LLM Provider for MoneyPrinter.

Supports multiple LLM backends through a unified interface:
  - Ollama (local, default)
  - OpenAI (cloud, requires API key)
  - Anthropic (cloud, requires API key)
  - Groq (cloud, requires API key)

Provider is selected via config.json "llm_provider" field or LLM_PROVIDER env var.
API keys are read from config with env-var fallbacks:
  OPENAI_API_KEY, ANTHROPIC_API_KEY, GROQ_API_KEY
"""

import os
import json
import importlib
from abc import ABC, abstractmethod

from config import (
    get_ollama_base_url,
    get_llm_provider,
    get_openai_api_key,
    get_anthropic_api_key,
    get_groq_api_key,
    get_openai_model,
    get_anthropic_model,
    get_groq_model,
)

# ---------------------------------------------------------------------------
# Provider interface
# ---------------------------------------------------------------------------

class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def list_models(self) -> list[str]:
        """Return available model names."""
        ...

    @abstractmethod
    def generate(self, prompt: str, model: str | None = None) -> str:
        """Generate text from a prompt. Returns the response string."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name."""
        ...


# ---------------------------------------------------------------------------
# Ollama provider (local)
# ---------------------------------------------------------------------------

class OllamaProvider(LLMProvider):
    """Local Ollama server provider."""

    def __init__(self):
        import ollama
        self._ollama = ollama
        self._host = get_ollama_base_url()

    def _client(self):
        return self._ollama.Client(host=self._host)

    @property
    def name(self) -> str:
        return "ollama"

    def list_models(self) -> list[str]:
        response = self._client().list()
        return sorted(m.model for m in response.models)

    def generate(self, prompt: str, model: str | None = None) -> str:
        if not model:
            raise RuntimeError("No model specified for Ollama.")
        response = self._client().chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response["message"]["content"].strip()


# ---------------------------------------------------------------------------
# OpenAI provider (cloud)
# ---------------------------------------------------------------------------

class OpenAIProvider(LLMProvider):
    """OpenAI API provider."""

    # Common models to list when API key is set
    _KNOWN_MODELS = [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-3.5-turbo",
        "o1",
        "o1-mini",
    ]

    def __init__(self):
        self._api_key = get_openai_api_key()
        if not self._api_key:
            raise ValueError(
                "OpenAI API key not configured. Set 'openai_api_key' in config.json "
                "or OPENAI_API_KEY environment variable."
            )
        self._default_model = get_openai_model()

    @property
    def name(self) -> str:
        return "openai"

    def list_models(self) -> list[str]:
        return list(self._KNOWN_MODELS)

    def generate(self, prompt: str, model: str | None = None) -> str:
        # Lazy import to avoid requiring openai when not used
        try:
            import openai
        except ImportError:
            raise ImportError(
                "The 'openai' package is required for OpenAI provider. "
                "Install it with: pip install openai"
            )

        client = openai.OpenAI(api_key=self._api_key)
        target_model = model or self._default_model

        response = client.chat.completions.create(
            model=target_model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Anthropic provider (cloud)
# ---------------------------------------------------------------------------

class AnthropicProvider(LLMProvider):
    """Anthropic Claude API provider."""

    _KNOWN_MODELS = [
        "claude-sonnet-4-6",
        "claude-haiku-4-5-20251001",
        "claude-opus-4-6",
    ]

    def __init__(self):
        self._api_key = get_anthropic_api_key()
        if not self._api_key:
            raise ValueError(
                "Anthropic API key not configured. Set 'anthropic_api_key' in config.json "
                "or ANTHROPIC_API_KEY environment variable."
            )
        self._default_model = get_anthropic_model()

    @property
    def name(self) -> str:
        return "anthropic"

    def list_models(self) -> list[str]:
        return list(self._KNOWN_MODELS)

    def generate(self, prompt: str, model: str | None = None) -> str:
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "The 'anthropic' package is required for Anthropic provider. "
                "Install it with: pip install anthropic"
            )

        client = anthropic.Anthropic(api_key=self._api_key)
        target_model = model or self._default_model

        response = client.messages.create(
            model=target_model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()


# ---------------------------------------------------------------------------
# Groq provider (cloud, fast inference)
# ---------------------------------------------------------------------------

class GroqProvider(LLMProvider):
    """Groq cloud inference provider."""

    _KNOWN_MODELS = [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "mixtral-8x7b-32768",
        "gemma2-9b-it",
    ]

    def __init__(self):
        self._api_key = get_groq_api_key()
        if not self._api_key:
            raise ValueError(
                "Groq API key not configured. Set 'groq_api_key' in config.json "
                "or GROQ_API_KEY environment variable."
            )
        self._default_model = get_groq_model()

    @property
    def name(self) -> str:
        return "groq"

    def list_models(self) -> list[str]:
        return list(self._KNOWN_MODELS)

    def generate(self, prompt: str, model: str | None = None) -> str:
        try:
            import groq
        except ImportError:
            raise ImportError(
                "The 'groq' package is required for Groq provider. "
                "Install it with: pip install groq"
            )

        client = groq.Groq(api_key=self._api_key)
        target_model = model or self._default_model

        response = client.chat.completions.create(
            model=target_model,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, type[LLMProvider]] = {
    "ollama": OllamaProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "groq": GroqProvider,
}


def get_available_providers() -> list[str]:
    """Return names of all registered provider types."""
    return list(_PROVIDERS.keys())


def create_provider(provider_name: str | None = None) -> LLMProvider:
    """
    Create and return an LLM provider instance.

    Args:
        provider_name: One of 'ollama', 'openai', 'anthropic', 'groq'.
                       Defaults to config value or 'ollama'.
    """
    name = (provider_name or get_llm_provider()).lower().strip()
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown LLM provider '{name}'. "
            f"Available: {', '.join(_PROVIDERS.keys())}"
        )
    return cls()


# ---------------------------------------------------------------------------
# Module-level state (backward-compatible API)
# ---------------------------------------------------------------------------

_selected_model: str | None = None
_active_provider: LLMProvider | None = None


def _get_provider() -> LLMProvider:
    """Get or create the active provider."""
    global _active_provider
    if _active_provider is None:
        _active_provider = create_provider()
    return _active_provider


def set_provider(provider_name: str) -> None:
    """Switch the active LLM provider."""
    global _active_provider
    _active_provider = create_provider(provider_name)


def list_models() -> list[str]:
    """Lists all models available from the active provider."""
    return _get_provider().list_models()


def select_model(model: str) -> None:
    """Sets the model to use for all subsequent generate_text calls."""
    global _selected_model
    _selected_model = model


def get_active_model() -> str | None:
    """Returns the currently selected model, or None if none has been selected."""
    return _selected_model


def get_provider_name() -> str:
    """Returns the name of the active provider."""
    return _get_provider().name


_MAX_PROMPT_LENGTH = 50000  # Cap prompt length to prevent excessive API costs


def generate_text(prompt: str, model_name: str = None) -> str:
    """
    Generates text using the active LLM provider.

    Args:
        prompt: User prompt
        model_name: Optional model name override

    Returns:
        Generated text string
    """
    model = model_name or _selected_model
    if not model:
        raise RuntimeError(
            "No model selected. Call select_model() first or pass model_name."
        )
    # Truncate excessively long prompts to prevent API cost abuse
    if len(prompt) > _MAX_PROMPT_LENGTH:
        prompt = prompt[:_MAX_PROMPT_LENGTH]
    return _get_provider().generate(prompt, model)
