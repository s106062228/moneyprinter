"""
Configuration management for MoneyPrinter.

Loads config.json once and caches it in memory. Supports environment variable
fallbacks for sensitive fields (API keys, credentials). Call reload_config()
to force a re-read from disk.
"""

import os
import sys
import json

from termcolor import colored

ROOT_DIR = os.path.dirname(sys.path[0])

# ---------------------------------------------------------------------------
# Internal config cache
# ---------------------------------------------------------------------------

_config_cache: dict | None = None
_config_path: str = os.path.join(ROOT_DIR, "config.json")


def _load_config() -> dict:
    """Loads and caches config.json. Subsequent calls return the cached copy."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    try:
        with open(_config_path, "r") as f:
            _config_cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(colored(f"[config] Failed to load config: {type(exc).__name__}", "red"))
        _config_cache = {}
    return _config_cache


def reload_config() -> dict:
    """Forces a re-read of config.json from disk and returns the new config."""
    global _config_cache
    _config_cache = None
    return _load_config()


def _get(key: str, default=None):
    """Helper to fetch a config value with an optional default."""
    return _load_config().get(key, default)


# ---------------------------------------------------------------------------
# Folder structure helpers
# ---------------------------------------------------------------------------

def assert_folder_structure() -> None:
    """
    Make sure that the necessary folder structure is present.

    Returns:
        None
    """
    mp_dir = os.path.join(ROOT_DIR, ".mp")
    if not os.path.exists(mp_dir):
        if get_verbose():
            print(colored("=> Creating .mp data folder", "green"))
        os.makedirs(mp_dir)


def get_first_time_running() -> bool:
    """
    Checks if the program is running for the first time by checking if .mp folder exists.

    Returns:
        exists (bool): True if the program is running for the first time, False otherwise
    """
    return not os.path.exists(os.path.join(ROOT_DIR, ".mp"))


# ---------------------------------------------------------------------------
# Config getters — all read from the in-memory cache
# ---------------------------------------------------------------------------

def get_email_credentials() -> dict:
    """Gets the email credentials from config. Falls back to env vars."""
    creds = _get("email", {})
    # Allow env-var overrides for sensitive fields
    if not creds.get("username"):
        creds["username"] = os.environ.get("MP_EMAIL_USERNAME", creds.get("username", ""))
    if not creds.get("password"):
        creds["password"] = os.environ.get("MP_EMAIL_PASSWORD", creds.get("password", ""))
    return creds


def get_verbose() -> bool:
    """Gets the verbose flag from the config."""
    return bool(_get("verbose", False))


def get_firefox_profile_path() -> str:
    """Gets the path to the Firefox profile."""
    return _get("firefox_profile", "")


def get_headless() -> bool:
    """Gets the headless flag from the config."""
    return bool(_get("headless", False))


def get_ollama_base_url() -> str:
    """Gets the Ollama base URL."""
    return _get("ollama_base_url", "http://127.0.0.1:11434")


def get_ollama_model() -> str:
    """Gets the Ollama model name from the config, or empty string if not set."""
    return _get("ollama_model", "")


def get_llm_provider() -> str:
    """Gets the LLM provider name. Defaults to 'ollama'."""
    configured = _get("llm_provider", "ollama")
    return os.environ.get("LLM_PROVIDER", configured)


def get_openai_api_key() -> str:
    """Gets the OpenAI API key with env-var fallback."""
    configured = _get("openai_api_key", "")
    return configured or os.environ.get("OPENAI_API_KEY", "")


def get_openai_model() -> str:
    """Gets the default OpenAI model name."""
    return _get("openai_model", "gpt-4o-mini")


def get_anthropic_api_key() -> str:
    """Gets the Anthropic API key with env-var fallback."""
    configured = _get("anthropic_api_key", "")
    return configured or os.environ.get("ANTHROPIC_API_KEY", "")


def get_anthropic_model() -> str:
    """Gets the default Anthropic model name."""
    return _get("anthropic_model", "claude-sonnet-4-6")


def get_groq_api_key() -> str:
    """Gets the Groq API key with env-var fallback."""
    configured = _get("groq_api_key", "")
    return configured or os.environ.get("GROQ_API_KEY", "")


def get_groq_model() -> str:
    """Gets the default Groq model name."""
    return _get("groq_model", "llama-3.3-70b-versatile")


def get_twitter_language() -> str:
    """Gets the Twitter language from the config."""
    return _get("twitter_language", "en")


def get_nanobanana2_api_base_url() -> str:
    """Gets the Nano Banana 2 (Gemini image) API base URL."""
    return _get(
        "nanobanana2_api_base_url",
        "https://generativelanguage.googleapis.com/v1beta",
    )


def get_nanobanana2_api_key() -> str:
    """Gets the Nano Banana 2 API key with env-var fallback."""
    configured = _get("nanobanana2_api_key", "")
    return configured or os.environ.get("GEMINI_API_KEY", "")


def get_nanobanana2_model() -> str:
    """Gets the Nano Banana 2 model name."""
    return _get("nanobanana2_model", "gemini-3.1-flash-image-preview")


def get_nanobanana2_aspect_ratio() -> str:
    """Gets the aspect ratio for Nano Banana 2 image generation."""
    return _get("nanobanana2_aspect_ratio", "9:16")


def get_threads() -> int:
    """Gets the thread count for video encoding (MoviePy). Clamped 1-32."""
    val = int(_get("threads", 2) or 2)
    return min(max(val, 1), 32)


def get_zip_url() -> str:
    """Gets the URL to the zip file containing background songs."""
    return _get("zip_url", "")


def get_is_for_kids() -> bool:
    """Gets the is-for-kids flag from the config."""
    return bool(_get("is_for_kids", False))


def get_google_maps_scraper_zip_url() -> str:
    """Gets the URL to the Google Maps scraper zip file."""
    return _get("google_maps_scraper", "")


def get_google_maps_scraper_niche() -> str:
    """Gets the niche for the Google Maps scraper."""
    return _get("google_maps_scraper_niche", "")


def get_scraper_timeout() -> int:
    """Gets the timeout for the scraper. Capped at 3600 seconds (1 hour)."""
    val = int(_get("scraper_timeout", 300) or 300)
    # Cap at 1 hour to prevent indefinite process hangs
    return min(max(val, 10), 3600)


def get_outreach_message_subject() -> str:
    """Gets the outreach message subject."""
    return _get("outreach_message_subject", "")


def get_outreach_message_body_file() -> str:
    """Gets the outreach message body file path."""
    return _get("outreach_message_body_file", "")


def get_tts_voice() -> str:
    """Gets the TTS voice from the config."""
    return _get("tts_voice", "Jasper")


def get_assemblyai_api_key() -> str:
    """Gets the AssemblyAI API key with env-var fallback."""
    configured = _get("assembly_ai_api_key", "")
    return configured or os.environ.get("ASSEMBLYAI_API_KEY", "")


def get_stt_provider() -> str:
    """Gets the configured STT provider."""
    return _get("stt_provider", "local_whisper")


def get_whisper_model() -> str:
    """Gets the local Whisper model name."""
    return _get("whisper_model", "base")


def get_whisper_device() -> str:
    """Gets the target device for Whisper inference."""
    return _get("whisper_device", "auto")


def get_whisper_compute_type() -> str:
    """Gets the compute type for Whisper inference."""
    return _get("whisper_compute_type", "int8")


# ---------------------------------------------------------------------------
# Subtitle helpers
# ---------------------------------------------------------------------------

def equalize_subtitles(srt_path: str, max_chars: int = 10) -> None:
    """
    Equalizes the subtitles in an SRT file.

    Args:
        srt_path (str): The path to the SRT file
        max_chars (int): The maximum amount of characters in a subtitle

    Returns:
        None
    """
    import srt_equalizer
    srt_equalizer.equalize_srt_file(srt_path, srt_path, max_chars)


# ---------------------------------------------------------------------------
# Font / ImageMagick helpers
# ---------------------------------------------------------------------------

def get_font() -> str:
    """Gets the font from the config."""
    return _get("font", "")


def get_fonts_dir() -> str:
    """Gets the fonts directory."""
    return os.path.join(ROOT_DIR, "fonts")


def get_imagemagick_path() -> str:
    """Gets the path to ImageMagick."""
    return _get("imagemagick_path", "")


def get_script_sentence_length() -> int:
    """Gets the forced script's sentence length. Defaults to 4."""
    val = _get("script_sentence_length")
    return int(val) if val is not None else 4


# ---------------------------------------------------------------------------
# Cache path helpers
# ---------------------------------------------------------------------------

def get_cache_path() -> str:
    """Gets the path to the cache directory."""
    return os.path.join(ROOT_DIR, ".mp")


def get_youtube_cache_path() -> str:
    """Gets the path to the YouTube cache file."""
    return os.path.join(ROOT_DIR, ".mp", "youtube.json")


def get_twitter_cache_path() -> str:
    """Gets the path to the Twitter cache file."""
    return os.path.join(ROOT_DIR, ".mp", "twitter.json")


def get_results_cache_path() -> str:
    """Gets the path to the scraper results cache file."""
    return _get("results_cache_path", os.path.join(ROOT_DIR, ".mp", "results.csv"))


# ---------------------------------------------------------------------------
# Webhook configuration
# ---------------------------------------------------------------------------

def get_webhook_config() -> dict:
    """Gets the webhook configuration block."""
    return _get("webhooks", {})


def get_discord_webhook_url() -> str:
    """Gets the Discord webhook URL with env-var fallback."""
    configured = get_webhook_config().get("discord_url", "")
    return configured or os.environ.get("DISCORD_WEBHOOK_URL", "")


def get_slack_webhook_url() -> str:
    """Gets the Slack webhook URL with env-var fallback."""
    configured = get_webhook_config().get("slack_url", "")
    return configured or os.environ.get("SLACK_WEBHOOK_URL", "")


def get_webhooks_enabled() -> bool:
    """Checks if webhook notifications are enabled."""
    return bool(get_webhook_config().get("enabled", False))


def get_webhook_notify_events() -> list:
    """Returns the list of event types that should trigger notifications."""
    default_events = [
        "video_generated", "video_uploaded", "tweet_posted",
        "pitch_shared", "error",
    ]
    return get_webhook_config().get("notify_on", default_events)


# ---------------------------------------------------------------------------
# SEO optimizer configuration
# ---------------------------------------------------------------------------

def get_seo_config() -> dict:
    """Gets the SEO optimizer configuration block."""
    return _get("seo", {})


def get_seo_enabled() -> bool:
    """Checks if SEO optimization is enabled."""
    return bool(get_seo_config().get("enabled", True))


def get_seo_platforms() -> list:
    """Gets the list of platforms to optimize SEO for."""
    return get_seo_config().get("platforms", ["youtube"])
