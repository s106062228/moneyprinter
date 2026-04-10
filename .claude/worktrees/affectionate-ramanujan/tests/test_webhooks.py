"""Tests for the webhook notification module."""

import json
import time
import pytest
from unittest.mock import patch, MagicMock

import webhooks


# ---------------------------------------------------------------------------
# URL validation tests
# ---------------------------------------------------------------------------

class TestValidateWebhookUrl:
    """Tests for _validate_webhook_url."""

    def test_valid_discord_url(self):
        assert webhooks._validate_webhook_url(
            "https://discord.com/api/webhooks/123/abc", "discord"
        )

    def test_valid_discord_url_discordapp(self):
        assert webhooks._validate_webhook_url(
            "https://discordapp.com/api/webhooks/123/abc", "discord"
        )

    def test_invalid_discord_url_wrong_host(self):
        assert not webhooks._validate_webhook_url(
            "https://evil.com/api/webhooks/123/abc", "discord"
        )

    def test_valid_slack_url(self):
        assert webhooks._validate_webhook_url(
            "https://hooks.slack.com/services/T00/B00/xxxx", "slack"
        )

    def test_invalid_slack_url_wrong_host(self):
        assert not webhooks._validate_webhook_url(
            "https://evil.com/services/T00/B00/xxxx", "slack"
        )

    def test_http_rejected(self):
        """Webhook URLs must use HTTPS."""
        assert not webhooks._validate_webhook_url(
            "http://discord.com/api/webhooks/123/abc", "discord"
        )

    def test_empty_string(self):
        assert not webhooks._validate_webhook_url("", "discord")

    def test_none_value(self):
        assert not webhooks._validate_webhook_url(None, "discord")

    def test_non_string(self):
        assert not webhooks._validate_webhook_url(12345, "slack")

    def test_no_netloc(self):
        assert not webhooks._validate_webhook_url("https://", "discord")


# ---------------------------------------------------------------------------
# Message formatting tests
# ---------------------------------------------------------------------------

class TestFormatDiscordPayload:
    """Tests for Discord payload formatting."""

    def test_basic_payload_structure(self):
        payload = webhooks._format_discord_payload(
            "video_generated", "youtube", "A new video was generated!"
        )
        assert "embeds" in payload
        assert payload["username"] == "MoneyPrinter"
        assert len(payload["embeds"]) == 1

    def test_embed_fields(self):
        payload = webhooks._format_discord_payload(
            "video_generated", "youtube", "Test message"
        )
        embed = payload["embeds"][0]
        assert "title" in embed
        assert "description" in embed
        assert embed["description"] == "Test message"
        assert "timestamp" in embed
        assert "footer" in embed

    def test_with_details(self):
        details = {"title": "My Video", "duration": "60s"}
        payload = webhooks._format_discord_payload(
            "video_uploaded", "youtube", "Uploaded!", details
        )
        embed = payload["embeds"][0]
        assert "fields" in embed
        assert len(embed["fields"]) == 2

    def test_details_truncated_at_10_fields(self):
        details = {f"key_{i}": f"val_{i}" for i in range(15)}
        payload = webhooks._format_discord_payload(
            "video_generated", "youtube", "Test", details
        )
        assert len(payload["embeds"][0]["fields"]) == 10

    def test_long_value_truncated(self):
        details = {"description": "x" * 500}
        payload = webhooks._format_discord_payload(
            "video_generated", "youtube", "Test", details
        )
        field_value = payload["embeds"][0]["fields"][0]["value"]
        assert len(field_value) <= 256

    def test_error_event_color(self):
        payload = webhooks._format_discord_payload(
            "error", "system", "Something broke"
        )
        assert payload["embeds"][0]["color"] == 0xFF0000


class TestFormatSlackPayload:
    """Tests for Slack payload formatting."""

    def test_basic_payload_structure(self):
        payload = webhooks._format_slack_payload(
            "tweet_posted", "twitter", "New tweet posted!"
        )
        assert "blocks" in payload
        assert len(payload["blocks"]) >= 2

    def test_header_block(self):
        payload = webhooks._format_slack_payload(
            "tweet_posted", "twitter", "Test"
        )
        header = payload["blocks"][0]
        assert header["type"] == "header"
        assert "Tweet Posted" in header["text"]["text"]

    def test_with_details(self):
        details = {"content": "Hello world"}
        payload = webhooks._format_slack_payload(
            "tweet_posted", "twitter", "Posted!", details
        )
        # Should have header, message section, details section, context
        assert len(payload["blocks"]) == 4

    def test_context_block(self):
        payload = webhooks._format_slack_payload(
            "video_generated", "youtube", "Done"
        )
        context = payload["blocks"][-1]
        assert context["type"] == "context"
        assert "MoneyPrinter" in context["elements"][0]["text"]


# ---------------------------------------------------------------------------
# Config helpers tests
# ---------------------------------------------------------------------------

class TestConfigHelpers:
    """Tests for webhook configuration helpers."""

    @patch("webhooks._get")
    def test_is_webhooks_enabled_true(self, mock_get):
        mock_get.return_value = {"enabled": True}
        assert webhooks.is_webhooks_enabled()

    @patch("webhooks._get")
    def test_is_webhooks_enabled_false(self, mock_get):
        mock_get.return_value = {"enabled": False}
        assert not webhooks.is_webhooks_enabled()

    @patch("webhooks._get")
    def test_is_webhooks_enabled_missing(self, mock_get):
        mock_get.return_value = {}
        assert not webhooks.is_webhooks_enabled()

    @patch("webhooks._get")
    def test_get_discord_webhook_url_from_config(self, mock_get):
        mock_get.return_value = {"discord_url": "https://discord.com/api/webhooks/123/abc"}
        url = webhooks.get_discord_webhook_url()
        assert url == "https://discord.com/api/webhooks/123/abc"

    @patch.dict("os.environ", {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/env/test"})
    @patch("webhooks._get")
    def test_get_discord_webhook_url_env_fallback(self, mock_get):
        mock_get.return_value = {}
        url = webhooks.get_discord_webhook_url()
        assert url == "https://discord.com/api/webhooks/env/test"

    @patch("webhooks._get")
    def test_get_notify_events_default(self, mock_get):
        mock_get.return_value = {}
        events = webhooks.get_notify_events()
        assert "video_generated" in events
        assert "error" in events

    @patch("webhooks._get")
    def test_get_notify_events_custom(self, mock_get):
        mock_get.return_value = {"notify_on": ["video_uploaded"]}
        events = webhooks.get_notify_events()
        assert events == ["video_uploaded"]


# ---------------------------------------------------------------------------
# Send function tests (mocked HTTP)
# ---------------------------------------------------------------------------

class TestSendDiscord:
    """Tests for _send_discord with mocked HTTP."""

    @patch("webhooks._requests.post")
    @patch("webhooks.get_discord_webhook_url")
    def test_successful_send(self, mock_url, mock_post):
        mock_url.return_value = "https://discord.com/api/webhooks/123/abc"
        mock_post.return_value = MagicMock(status_code=204)

        result = webhooks._send_discord("video_generated", "youtube", "Test!")
        assert result is True
        mock_post.assert_called_once()

    @patch("webhooks._requests.post")
    @patch("webhooks.get_discord_webhook_url")
    def test_failed_send_bad_status(self, mock_url, mock_post):
        mock_url.return_value = "https://discord.com/api/webhooks/123/abc"
        mock_post.return_value = MagicMock(status_code=400)

        result = webhooks._send_discord("video_generated", "youtube", "Test!")
        assert result is False

    @patch("webhooks._requests.post")
    @patch("webhooks.get_discord_webhook_url")
    def test_network_error(self, mock_url, mock_post):
        mock_url.return_value = "https://discord.com/api/webhooks/123/abc"
        mock_post.side_effect = ConnectionError("Network down")

        result = webhooks._send_discord("error", "system", "Network issue")
        assert result is False

    @patch("webhooks.get_discord_webhook_url")
    def test_invalid_url_skipped(self, mock_url):
        mock_url.return_value = "http://evil.com/webhook"
        result = webhooks._send_discord("video_generated", "youtube", "Test!")
        assert result is False


class TestSendSlack:
    """Tests for _send_slack with mocked HTTP."""

    @patch("webhooks._requests.post")
    @patch("webhooks.get_slack_webhook_url")
    def test_successful_send(self, mock_url, mock_post):
        mock_url.return_value = "https://hooks.slack.com/services/T00/B00/xxxx"
        mock_post.return_value = MagicMock(status_code=200)

        result = webhooks._send_slack("tweet_posted", "twitter", "Posted!")
        assert result is True

    @patch("webhooks._requests.post")
    @patch("webhooks.get_slack_webhook_url")
    def test_failed_send(self, mock_url, mock_post):
        mock_url.return_value = "https://hooks.slack.com/services/T00/B00/xxxx"
        mock_post.return_value = MagicMock(status_code=500)

        result = webhooks._send_slack("error", "system", "Oops")
        assert result is False

    @patch("webhooks.get_slack_webhook_url")
    def test_invalid_url_skipped(self, mock_url):
        mock_url.return_value = "https://evil.com/services"
        result = webhooks._send_slack("tweet_posted", "twitter", "Test!")
        assert result is False


# ---------------------------------------------------------------------------
# Public API tests
# ---------------------------------------------------------------------------

class TestNotify:
    """Tests for the public notify() function."""

    @patch("webhooks.is_webhooks_enabled")
    def test_disabled_returns_empty(self, mock_enabled):
        mock_enabled.return_value = False
        result = webhooks.notify("video_generated", "youtube", "Test")
        assert result == {}

    @patch("webhooks.get_notify_events")
    @patch("webhooks.is_webhooks_enabled")
    def test_event_not_in_list_returns_empty(self, mock_enabled, mock_events):
        mock_enabled.return_value = True
        mock_events.return_value = ["video_uploaded"]
        result = webhooks.notify("video_generated", "youtube", "Test")
        assert result == {}

    @patch("webhooks._send_discord")
    @patch("webhooks.get_discord_webhook_url")
    @patch("webhooks.get_slack_webhook_url")
    @patch("webhooks.get_notify_events")
    @patch("webhooks.is_webhooks_enabled")
    def test_sends_to_discord_only(
        self, mock_enabled, mock_events, mock_slack, mock_discord_url, mock_send
    ):
        mock_enabled.return_value = True
        mock_events.return_value = ["video_generated"]
        mock_discord_url.return_value = "https://discord.com/api/webhooks/123/abc"
        mock_slack.return_value = ""
        mock_send.return_value = True

        result = webhooks.notify("video_generated", "youtube", "Done!")
        assert result == {"discord": True}

    @patch("webhooks._send_slack")
    @patch("webhooks._send_discord")
    @patch("webhooks.get_discord_webhook_url")
    @patch("webhooks.get_slack_webhook_url")
    @patch("webhooks.get_notify_events")
    @patch("webhooks.is_webhooks_enabled")
    def test_sends_to_both_providers(
        self, mock_enabled, mock_events, mock_slack_url,
        mock_discord_url, mock_send_discord, mock_send_slack
    ):
        mock_enabled.return_value = True
        mock_events.return_value = ["video_uploaded"]
        mock_discord_url.return_value = "https://discord.com/api/webhooks/123/abc"
        mock_slack_url.return_value = "https://hooks.slack.com/services/T00/B00/xxxx"
        mock_send_discord.return_value = True
        mock_send_slack.return_value = True

        result = webhooks.notify("video_uploaded", "youtube", "Uploaded!")
        assert result == {"discord": True, "slack": True}


class TestNotifyError:
    """Tests for the notify_error() convenience function."""

    @patch("webhooks.notify")
    def test_calls_notify_with_error_type(self, mock_notify):
        mock_notify.return_value = {"discord": True}
        result = webhooks.notify_error("Something went wrong", platform="youtube")
        mock_notify.assert_called_once_with(
            "error", "youtube", "Something went wrong", None
        )

    @patch("webhooks.notify")
    def test_default_platform_is_system(self, mock_notify):
        mock_notify.return_value = {}
        webhooks.notify_error("Oops")
        mock_notify.assert_called_once_with("error", "system", "Oops", None)
