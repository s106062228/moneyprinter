"""
Webhook notification module for MoneyPrinter.

Sends real-time notifications to Discord and/or Slack when content is
generated, uploaded, or when errors occur. Integrates with the analytics
module for event-driven notifications.

Configuration (config.json):
    "webhooks": {
        "discord_url": "https://discord.com/api/webhooks/...",
        "slack_url": "https://hooks.slack.com/services/...",
        "enabled": true,
        "notify_on": ["video_generated", "video_uploaded", "tweet_posted",
                       "pitch_shared", "error"]
    }

Security:
    - Webhook URLs are treated as secrets (env var fallbacks supported)
    - URLs are validated before use
    - Timeouts enforced on all HTTP requests
    - No webhook URL or sensitive data included in error messages
    - Rate limiting to prevent flooding (max 1 message per second per provider)
"""

import os
import json
import time
import threading
import requests as _requests
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from config import _get
from mp_logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

_MIN_SEND_INTERVAL = 1.0  # seconds between webhook sends per provider
_last_send_time: dict[str, float] = {}
_send_lock = threading.Lock()


def _rate_limit(provider: str) -> None:
    """Enforces minimum interval between sends for a given provider."""
    with _send_lock:
        now = time.monotonic()
        last = _last_send_time.get(provider, 0.0)
        elapsed = now - last
        if elapsed < _MIN_SEND_INTERVAL:
            time.sleep(_MIN_SEND_INTERVAL - elapsed)
        _last_send_time[provider] = time.monotonic()


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _get_webhook_config() -> dict:
    """Returns the webhooks configuration block."""
    return _get("webhooks", {})


def get_discord_webhook_url() -> str:
    """Gets the Discord webhook URL with env-var fallback."""
    configured = _get_webhook_config().get("discord_url", "")
    return configured or os.environ.get("DISCORD_WEBHOOK_URL", "")


def get_slack_webhook_url() -> str:
    """Gets the Slack webhook URL with env-var fallback."""
    configured = _get_webhook_config().get("slack_url", "")
    return configured or os.environ.get("SLACK_WEBHOOK_URL", "")


def is_webhooks_enabled() -> bool:
    """Checks if webhook notifications are enabled."""
    return bool(_get_webhook_config().get("enabled", False))


def get_notify_events() -> list[str]:
    """Returns the list of event types that should trigger notifications."""
    default_events = [
        "video_generated",
        "video_uploaded",
        "tweet_posted",
        "pitch_shared",
        "error",
    ]
    return _get_webhook_config().get("notify_on", default_events)


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------

def _validate_webhook_url(url: str, provider: str) -> bool:
    """
    Validates a webhook URL for a given provider.

    Args:
        url: The webhook URL to validate.
        provider: 'discord' or 'slack'.

    Returns:
        True if the URL is valid for the provider, False otherwise.
    """
    if not url or not isinstance(url, str):
        return False

    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False

    if parsed.scheme != "https":
        logger.warning("Webhook URL must use HTTPS.")
        return False

    if not parsed.netloc:
        return False

    # Provider-specific host validation
    if provider == "discord":
        if "discord.com" not in parsed.netloc and "discordapp.com" not in parsed.netloc:
            logger.warning("Discord webhook URL must be on discord.com or discordapp.com.")
            return False
    elif provider == "slack":
        if "hooks.slack.com" not in parsed.netloc:
            logger.warning("Slack webhook URL must be on hooks.slack.com.")
            return False

    return True


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------

_EVENT_EMOJIS = {
    "video_generated": "\U0001f3ac",  # 🎬
    "video_uploaded": "\U0001f680",   # 🚀
    "tweet_posted": "\U0001f426",     # 🐦
    "pitch_shared": "\U0001f4b0",     # 💰
    "error": "\u274c",                # ❌
    "outreach_sent": "\U0001f4e7",    # 📧
    "tiktok_uploaded": "\U0001f3b5",  # 🎵
}


def _format_discord_payload(
    event_type: str,
    platform: str,
    message: str,
    details: Optional[dict] = None,
) -> dict:
    """
    Formats a Discord webhook payload with an embed.

    Returns:
        dict: The JSON payload for Discord's webhook API.
    """
    emoji = _EVENT_EMOJIS.get(event_type, "\U0001f514")  # 🔔 default
    color_map = {
        "video_generated": 0x00FF00,  # green
        "video_uploaded": 0x0099FF,   # blue
        "tweet_posted": 0x1DA1F2,     # twitter blue
        "pitch_shared": 0xFFD700,     # gold
        "error": 0xFF0000,            # red
        "outreach_sent": 0x9B59B6,    # purple
        "tiktok_uploaded": 0xFF0050,   # tiktok pink
    }

    embed = {
        "title": f"{emoji} {event_type.replace('_', ' ').title()}",
        "description": message,
        "color": color_map.get(event_type, 0x808080),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "footer": {"text": f"MoneyPrinter • {platform}"},
    }

    if details:
        fields = []
        for key, value in list(details.items())[:10]:  # limit fields
            fields.append({
                "name": str(key).replace("_", " ").title(),
                "value": str(value)[:256],  # truncate long values
                "inline": True,
            })
        embed["fields"] = fields

    return {
        "username": "MoneyPrinter",
        "embeds": [embed],
    }


def _format_slack_payload(
    event_type: str,
    platform: str,
    message: str,
    details: Optional[dict] = None,
) -> dict:
    """
    Formats a Slack webhook payload with blocks.

    Returns:
        dict: The JSON payload for Slack's incoming webhook API.
    """
    emoji = _EVENT_EMOJIS.get(event_type, ":bell:")

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} {event_type.replace('_', ' ').title()}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": message,
            },
        },
    ]

    if details:
        detail_lines = []
        for key, value in list(details.items())[:10]:
            detail_lines.append(
                f"*{str(key).replace('_', ' ').title()}:* {str(value)[:256]}"
            )
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "\n".join(detail_lines),
            },
        })

    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"MoneyPrinter • {platform} • {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            }
        ],
    })

    return {"blocks": blocks}


# ---------------------------------------------------------------------------
# Sending functions
# ---------------------------------------------------------------------------

def _send_discord(
    event_type: str,
    platform: str,
    message: str,
    details: Optional[dict] = None,
) -> bool:
    """
    Sends a notification to Discord.

    Returns:
        True if the message was sent successfully, False otherwise.
    """
    url = get_discord_webhook_url()
    if not _validate_webhook_url(url, "discord"):
        return False

    payload = _format_discord_payload(event_type, platform, message, details)

    try:
        _rate_limit("discord")
        response = _requests.post(
            url,
            json=payload,
            timeout=10,
            headers={"Content-Type": "application/json"},
        )
        # Discord returns 204 No Content on success
        if response.status_code in (200, 204):
            logger.debug("Discord notification sent successfully.")
            return True
        else:
            logger.warning(
                f"Discord webhook returned status {response.status_code}."
            )
            return False
    except Exception as e:
        logger.warning(f"Failed to send Discord notification: {type(e).__name__}")
        return False


def _send_slack(
    event_type: str,
    platform: str,
    message: str,
    details: Optional[dict] = None,
) -> bool:
    """
    Sends a notification to Slack.

    Returns:
        True if the message was sent successfully, False otherwise.
    """
    url = get_slack_webhook_url()
    if not _validate_webhook_url(url, "slack"):
        return False

    payload = _format_slack_payload(event_type, platform, message, details)

    try:
        _rate_limit("slack")
        response = _requests.post(
            url,
            json=payload,
            timeout=10,
            headers={"Content-Type": "application/json"},
        )
        if response.status_code == 200:
            logger.debug("Slack notification sent successfully.")
            return True
        else:
            logger.warning(
                f"Slack webhook returned status {response.status_code}."
            )
            return False
    except Exception as e:
        logger.warning(f"Failed to send Slack notification: {type(e).__name__}")
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def notify(
    event_type: str,
    platform: str,
    message: str,
    details: Optional[dict] = None,
) -> dict[str, bool]:
    """
    Sends a webhook notification to all configured providers.

    This is the main entry point for sending notifications. It checks whether
    webhooks are enabled and whether the event type should trigger a notification,
    then dispatches to all configured providers.

    Args:
        event_type: Type of event (e.g., "video_generated", "video_uploaded").
        platform: Target platform ("youtube", "twitter", "tiktok", etc.).
        message: Human-readable description of the event.
        details: Optional dict with extra metadata.

    Returns:
        Dict mapping provider name to success boolean.
        Empty dict if webhooks are disabled or event type not in notify list.
    """
    if not is_webhooks_enabled():
        return {}

    if event_type not in get_notify_events():
        return {}

    results: dict[str, bool] = {}

    discord_url = get_discord_webhook_url()
    if discord_url:
        results["discord"] = _send_discord(event_type, platform, message, details)

    slack_url = get_slack_webhook_url()
    if slack_url:
        results["slack"] = _send_slack(event_type, platform, message, details)

    return results


def notify_error(
    error_message: str,
    platform: str = "system",
    details: Optional[dict] = None,
) -> dict[str, bool]:
    """
    Convenience function for sending error notifications.

    Args:
        error_message: Description of the error.
        platform: Which platform/module the error occurred in.
        details: Optional extra metadata.

    Returns:
        Dict mapping provider name to success boolean.
    """
    return notify("error", platform, error_message, details)
