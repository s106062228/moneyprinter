"""
Instagram Reels upload automation for MoneyPrinter.

Uses the instagrapi library for uploading Reels to Instagram.
Supports caption generation, hashtag injection, and thumbnail selection.

Usage:
    from classes.Instagram import Instagram

    ig = Instagram(
        account_id="abc123",
        nickname="my_account",
        username="my_ig_user",
        password="my_ig_pass",
    )
    ig.upload_reel(
        video_path="/path/to/video.mp4",
        caption="My awesome reel! #content #ai",
    )

Configuration (config.json):
    "instagram": {
        "username": "",
        "password": ""
    }

Security:
    - Credentials support env-var fallbacks (IG_USERNAME, IG_PASSWORD)
    - No credentials are logged or included in error messages
    - Video paths are validated before upload
    - Caption length is capped to Instagram's 2200 char limit
    - Session files are stored in .mp/ directory (gitignored)
"""

import os
import json
import tempfile
from datetime import datetime
from typing import Optional

from config import _get, ROOT_DIR
from mp_logger import get_logger
from status import success, error, warning, info
from validation import validate_path

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants and limits
# ---------------------------------------------------------------------------

_MAX_CAPTION_LENGTH = 2200
_MAX_HASHTAGS = 30
_MAX_VIDEO_DURATION = 900  # 15 minutes in seconds
_SESSION_DIR = os.path.join(ROOT_DIR, ".mp", "ig_sessions")

# Allowed video extensions
_ALLOWED_VIDEO_EXTENSIONS = (".mp4", ".mov")


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _get_instagram_config() -> dict:
    """Returns the Instagram configuration block."""
    return _get("instagram", {})


def get_instagram_username() -> str:
    """Gets the Instagram username with env-var fallback."""
    configured = _get_instagram_config().get("username", "")
    return configured or os.environ.get("IG_USERNAME", "")


def get_instagram_password() -> str:
    """Gets the Instagram password with env-var fallback."""
    configured = _get_instagram_config().get("password", "")
    return configured or os.environ.get("IG_PASSWORD", "")


# ---------------------------------------------------------------------------
# Cache helpers (atomic read/write for Instagram account data)
# ---------------------------------------------------------------------------

def _get_ig_cache_path() -> str:
    """Returns the path to the Instagram cache file."""
    return os.path.join(ROOT_DIR, ".mp", "instagram.json")


def _safe_read_cache() -> dict:
    """Reads Instagram cache data (TOCTOU-safe)."""
    try:
        with open(_get_ig_cache_path(), "r") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {"accounts": [], "reels": []}
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        return {"accounts": [], "reels": []}


def _safe_write_cache(data: dict) -> None:
    """Atomically writes Instagram cache data."""
    cache_path = _get_ig_cache_path()
    dir_name = os.path.dirname(cache_path)
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, cache_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Instagram Reels Class
# ---------------------------------------------------------------------------

class Instagram:
    """
    Handles Instagram Reels upload automation via instagrapi.

    Supports:
        - Reel upload with caption and hashtags
        - Session persistence for avoiding repeated logins
        - Atomic cache writes for upload history
        - Input validation on all user-provided data
    """

    def __init__(
        self,
        account_id: str,
        nickname: str,
        username: str = "",
        password: str = "",
    ):
        """
        Initialize the Instagram handler.

        Args:
            account_id: Unique account identifier.
            nickname: Human-readable account nickname.
            username: Instagram username (falls back to config/env).
            password: Instagram password (falls back to config/env).
        """
        self.account_id = account_id
        self.nickname = nickname
        self.username = username or get_instagram_username()
        self.password = password or get_instagram_password()
        self._client = None

        if not self.username or not self.password:
            raise ValueError(
                "Instagram credentials not configured. "
                "Set 'instagram.username' and 'instagram.password' in config.json "
                "or use IG_USERNAME and IG_PASSWORD environment variables."
            )

    def _get_client(self):
        """
        Returns an authenticated instagrapi Client.

        Attempts to load a saved session first to avoid re-authentication.
        Falls back to fresh login if session is expired.
        """
        if self._client is not None:
            return self._client

        try:
            from instagrapi import Client
        except ImportError:
            raise ImportError(
                "The 'instagrapi' package is required for Instagram integration. "
                "Install it with: pip install instagrapi"
            )

        client = Client()

        # Attempt to load saved session
        session_path = self._get_session_path()
        if os.path.isfile(session_path):
            try:
                client.load_settings(session_path)
                client.login(self.username, self.password)
                # Verify session is still valid
                client.get_timeline_feed()
                self._client = client
                logger.info("Instagram session restored for account '%s'.", self.nickname)
                return self._client
            except Exception:
                logger.debug("Saved session expired, performing fresh login.")

        # Fresh login
        try:
            client.login(self.username, self.password)
        except Exception as e:
            raise RuntimeError(
                f"Instagram login failed: {type(e).__name__}. "
                "Check credentials and try again."
            )

        # Save session for future use
        self._save_session(client, session_path)

        self._client = client
        logger.info("Instagram login successful for account '%s'.", self.nickname)
        return self._client

    def _get_session_path(self) -> str:
        """Returns the path to the session settings file for this account."""
        os.makedirs(_SESSION_DIR, exist_ok=True)
        # Use account_id as filename to avoid path injection
        safe_id = "".join(c for c in self.account_id if c.isalnum() or c in ("-", "_"))
        if not safe_id:
            safe_id = "default"
        return os.path.join(_SESSION_DIR, f"{safe_id[:50]}_session.json")

    def _save_session(self, client, session_path: str) -> None:
        """Saves the instagrapi client session atomically."""
        try:
            os.makedirs(os.path.dirname(session_path), exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                dir=os.path.dirname(session_path), suffix=".tmp"
            )
            try:
                os.close(fd)
                client.dump_settings(tmp_path)
                os.replace(tmp_path, session_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception as e:
            logger.warning(
                "Failed to save Instagram session: %s", type(e).__name__
            )

    def upload_reel(
        self,
        video_path: str,
        caption: str = "",
        thumbnail_path: Optional[str] = None,
    ) -> bool:
        """
        Uploads a video as an Instagram Reel.

        Args:
            video_path: Path to the video file (.mp4 or .mov).
            caption: Reel caption (max 2200 chars).
            thumbnail_path: Optional custom thumbnail image path.

        Returns:
            True if upload was successful, False otherwise.

        Raises:
            ValueError: If inputs are invalid.
            ImportError: If instagrapi is not installed.
        """
        # Validate video path
        if not video_path or not isinstance(video_path, str):
            raise ValueError("video_path must be a non-empty string.")
        if "\x00" in video_path:
            raise ValueError("video_path contains null bytes.")
        if not os.path.isfile(video_path):
            raise ValueError("Video file does not exist at the specified path.")

        # Validate file extension
        ext = os.path.splitext(video_path)[1].lower()
        if ext not in _ALLOWED_VIDEO_EXTENSIONS:
            raise ValueError(
                f"Unsupported video format '{ext}'. "
                f"Supported: {', '.join(_ALLOWED_VIDEO_EXTENSIONS)}"
            )

        # Truncate caption to Instagram's limit
        if caption and len(caption) > _MAX_CAPTION_LENGTH:
            caption = caption[:_MAX_CAPTION_LENGTH - 3].rsplit(" ", 1)[0] + "..."

        try:
            client = self._get_client()

            info(f" => Uploading Reel to Instagram (@{self.nickname})...")

            # Upload the reel
            kwargs = {
                "path": video_path,
                "caption": caption or "",
            }

            if thumbnail_path and os.path.isfile(thumbnail_path):
                kwargs["thumbnail"] = thumbnail_path

            media = client.clip_upload(**kwargs)

            if media:
                reel_id = str(media.pk)
                success(f" => Reel uploaded successfully! (ID: {reel_id})")

                # Track in cache
                self._record_upload(video_path, caption, reel_id)

                # Track analytics
                self._track_analytics(reel_id, caption)

                return True
            else:
                warning(" => Reel upload returned no media object.")
                return False

        except ImportError:
            raise
        except Exception as e:
            logger.warning("Instagram Reel upload failed: %s", type(e).__name__)
            error(f" => Instagram upload failed: {type(e).__name__}")
            return False

    def get_reels(self) -> list:
        """
        Returns the list of previously uploaded reels from cache.

        Returns:
            List of reel dicts with keys: date, caption, reel_id.
        """
        data = _safe_read_cache()
        account_reels = [
            r for r in data.get("reels", [])
            if r.get("account_id") == self.account_id
        ]
        return account_reels

    def _record_upload(
        self, video_path: str, caption: str, reel_id: str
    ) -> None:
        """Records a reel upload in the cache (atomic write)."""
        data = _safe_read_cache()
        if "reels" not in data:
            data["reels"] = []

        data["reels"].append({
            "account_id": self.account_id,
            "date": datetime.now().isoformat(),
            "caption": caption[:200],  # Truncate for cache storage
            "reel_id": reel_id,
        })

        # Cap cache size to prevent unbounded growth
        if len(data["reels"]) > 5000:
            data["reels"] = data["reels"][-5000:]

        _safe_write_cache(data)

    def _track_analytics(self, reel_id: str, caption: str) -> None:
        """Tracks the reel upload in the analytics module."""
        try:
            from analytics import track_event
            track_event(
                event_type="reel_uploaded",
                platform="instagram",
                details={
                    "reel_id": reel_id,
                    "caption_length": len(caption),
                    "account": self.nickname,
                },
            )
        except Exception as e:
            logger.debug(
                "Failed to track Instagram analytics: %s", type(e).__name__
            )

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit — no browser to clean up (API-based)."""
        self._client = None
        return False
