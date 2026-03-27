"""Tests for the Instagram Reels module."""

import os
import json
import tempfile
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from datetime import datetime

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ---------------------------------------------------------------------------
# Configuration helper tests
# ---------------------------------------------------------------------------

class TestInstagramConfigHelpers:
    """Tests for Instagram configuration helper functions."""

    @patch("classes.Instagram._get")
    def test_get_instagram_config_returns_dict(self, mock_get):
        from classes.Instagram import _get_instagram_config
        mock_get.return_value = {"username": "user", "password": "pass"}
        result = _get_instagram_config()
        assert isinstance(result, dict)
        mock_get.assert_called_once_with("instagram", {})

    @patch("classes.Instagram._get")
    def test_get_instagram_config_default_empty(self, mock_get):
        from classes.Instagram import _get_instagram_config
        mock_get.return_value = {}
        result = _get_instagram_config()
        assert result == {}

    @patch("classes.Instagram._get_instagram_config")
    def test_get_instagram_username_from_config(self, mock_config):
        from classes.Instagram import get_instagram_username
        mock_config.return_value = {"username": "myuser"}
        result = get_instagram_username()
        assert result == "myuser"

    @patch("classes.Instagram._get_instagram_config")
    def test_get_instagram_username_env_fallback(self, mock_config):
        from classes.Instagram import get_instagram_username
        mock_config.return_value = {"username": ""}
        with patch.dict(os.environ, {"IG_USERNAME": "envuser"}):
            result = get_instagram_username()
        assert result == "envuser"

    @patch("classes.Instagram._get_instagram_config")
    def test_get_instagram_username_empty_when_not_set(self, mock_config):
        from classes.Instagram import get_instagram_username
        mock_config.return_value = {}
        with patch.dict(os.environ, {}, clear=True):
            # Remove IG_USERNAME if present
            os.environ.pop("IG_USERNAME", None)
            result = get_instagram_username()
        assert result == ""

    @patch("classes.Instagram._get_instagram_config")
    def test_get_instagram_password_from_config(self, mock_config):
        from classes.Instagram import get_instagram_password
        mock_config.return_value = {"password": "secret123"}
        result = get_instagram_password()
        assert result == "secret123"

    @patch("classes.Instagram._get_instagram_config")
    def test_get_instagram_password_env_fallback(self, mock_config):
        from classes.Instagram import get_instagram_password
        mock_config.return_value = {"password": ""}
        with patch.dict(os.environ, {"IG_PASSWORD": "envpass"}):
            result = get_instagram_password()
        assert result == "envpass"


# ---------------------------------------------------------------------------
# Cache helper tests
# ---------------------------------------------------------------------------

class TestInstagramCacheHelpers:
    """Tests for Instagram cache read/write functions."""

    @patch("classes.Instagram.ROOT_DIR", "/tmp/test_mp")
    def test_get_ig_cache_path(self):
        from classes.Instagram import _get_ig_cache_path
        path = _get_ig_cache_path()
        assert path.endswith("instagram.json")
        assert ".mp" in path

    def test_safe_read_cache_missing_file(self, tmp_path):
        """Returns default when file doesn't exist."""
        from classes.Instagram import _safe_read_cache
        with patch("classes.Instagram._get_ig_cache_path", return_value=str(tmp_path / "nonexistent.json")):
            result = _safe_read_cache()
        assert result == {"accounts": [], "reels": []}

    def test_safe_read_cache_invalid_json(self, tmp_path):
        """Returns default when file contains invalid JSON."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json{{{")
        from classes.Instagram import _safe_read_cache
        with patch("classes.Instagram._get_ig_cache_path", return_value=str(bad_file)):
            result = _safe_read_cache()
        assert result == {"accounts": [], "reels": []}

    def test_safe_read_cache_valid_data(self, tmp_path):
        """Returns parsed data from valid JSON file."""
        good_file = tmp_path / "good.json"
        data = {"accounts": [{"id": "1"}], "reels": [{"reel_id": "abc"}]}
        good_file.write_text(json.dumps(data))
        from classes.Instagram import _safe_read_cache
        with patch("classes.Instagram._get_ig_cache_path", return_value=str(good_file)):
            result = _safe_read_cache()
        assert result == data

    def test_safe_read_cache_non_dict_returns_default(self, tmp_path):
        """Returns default when file contains non-dict JSON."""
        arr_file = tmp_path / "arr.json"
        arr_file.write_text("[1, 2, 3]")
        from classes.Instagram import _safe_read_cache
        with patch("classes.Instagram._get_ig_cache_path", return_value=str(arr_file)):
            result = _safe_read_cache()
        assert result == {"accounts": [], "reels": []}

    def test_safe_write_cache_creates_file(self, tmp_path):
        """Writes data atomically to cache file."""
        cache_path = str(tmp_path / "cache" / "instagram.json")
        from classes.Instagram import _safe_write_cache
        with patch("classes.Instagram._get_ig_cache_path", return_value=cache_path):
            _safe_write_cache({"accounts": [], "reels": [{"id": "test"}]})
        assert os.path.isfile(cache_path)
        with open(cache_path) as f:
            data = json.load(f)
        assert len(data["reels"]) == 1
        assert data["reels"][0]["id"] == "test"

    def test_safe_write_cache_overwrites_existing(self, tmp_path):
        """Overwrites existing cache file atomically."""
        cache_path = str(tmp_path / "instagram.json")
        with open(cache_path, "w") as f:
            json.dump({"reels": [{"old": True}]}, f)
        from classes.Instagram import _safe_write_cache
        with patch("classes.Instagram._get_ig_cache_path", return_value=cache_path):
            _safe_write_cache({"reels": [{"new": True}]})
        with open(cache_path) as f:
            data = json.load(f)
        assert data["reels"][0].get("new") is True


# ---------------------------------------------------------------------------
# Instagram class initialization tests
# ---------------------------------------------------------------------------

class TestInstagramInit:
    """Tests for Instagram class __init__."""

    @patch("classes.Instagram.get_instagram_username", return_value="user")
    @patch("classes.Instagram.get_instagram_password", return_value="pass")
    def test_init_with_explicit_credentials(self, mock_pw, mock_un):
        from classes.Instagram import Instagram
        ig = Instagram("id1", "nick", "myuser", "mypass")
        assert ig.account_id == "id1"
        assert ig.nickname == "nick"
        assert ig.username == "myuser"
        assert ig.password == "mypass"
        assert ig._client is None

    @patch("classes.Instagram.get_instagram_username", return_value="cfguser")
    @patch("classes.Instagram.get_instagram_password", return_value="cfgpass")
    def test_init_fallback_to_config(self, mock_pw, mock_un):
        from classes.Instagram import Instagram
        ig = Instagram("id2", "nick2")
        assert ig.username == "cfguser"
        assert ig.password == "cfgpass"

    @patch("classes.Instagram.get_instagram_username", return_value="")
    @patch("classes.Instagram.get_instagram_password", return_value="")
    def test_init_no_credentials_raises(self, mock_pw, mock_un):
        from classes.Instagram import Instagram
        with pytest.raises(ValueError, match="credentials not configured"):
            Instagram("id3", "nick3")

    @patch("classes.Instagram.get_instagram_username", return_value="user")
    @patch("classes.Instagram.get_instagram_password", return_value="")
    def test_init_missing_password_raises(self, mock_pw, mock_un):
        from classes.Instagram import Instagram
        with pytest.raises(ValueError, match="credentials not configured"):
            Instagram("id4", "nick4")


# ---------------------------------------------------------------------------
# Session path tests
# ---------------------------------------------------------------------------

class TestSessionPath:
    """Tests for session file path generation."""

    @patch("classes.Instagram.get_instagram_username", return_value="u")
    @patch("classes.Instagram.get_instagram_password", return_value="p")
    @patch("classes.Instagram._SESSION_DIR", "/tmp/test_sessions")
    def test_session_path_uses_account_id(self, mock_pw, mock_un):
        from classes.Instagram import Instagram
        ig = Instagram("my-account-123", "nick")
        with patch("os.makedirs"):
            path = ig._get_session_path()
        assert "my-account-123_session.json" in path

    @patch("classes.Instagram.get_instagram_username", return_value="u")
    @patch("classes.Instagram.get_instagram_password", return_value="p")
    @patch("classes.Instagram._SESSION_DIR", "/tmp/test_sessions")
    def test_session_path_sanitizes_special_chars(self, mock_pw, mock_un):
        from classes.Instagram import Instagram
        ig = Instagram("../../../etc/passwd", "nick")
        with patch("os.makedirs"):
            path = ig._get_session_path()
        assert ".." not in os.path.basename(path)
        assert "/" not in os.path.basename(path).replace("_session.json", "")

    @patch("classes.Instagram.get_instagram_username", return_value="u")
    @patch("classes.Instagram.get_instagram_password", return_value="p")
    @patch("classes.Instagram._SESSION_DIR", "/tmp/test_sessions")
    def test_session_path_empty_id_uses_default(self, mock_pw, mock_un):
        from classes.Instagram import Instagram
        ig = Instagram("!!@@##", "nick")
        with patch("os.makedirs"):
            path = ig._get_session_path()
        assert "_session.json" in path
        assert "acct_" in path

    @patch("classes.Instagram.get_instagram_username", return_value="u")
    @patch("classes.Instagram.get_instagram_password", return_value="p")
    @patch("classes.Instagram._SESSION_DIR", "/tmp/test_sessions")
    def test_session_path_truncates_long_id(self, mock_pw, mock_un):
        from classes.Instagram import Instagram
        ig = Instagram("a" * 200, "nick")
        with patch("os.makedirs"):
            path = ig._get_session_path()
        basename = os.path.basename(path).replace("_session.json", "")
        assert len(basename) <= 50


# ---------------------------------------------------------------------------
# upload_reel validation tests
# ---------------------------------------------------------------------------

class TestUploadReelValidation:
    """Tests for upload_reel input validation."""

    def _make_ig(self):
        with patch("classes.Instagram.get_instagram_username", return_value="u"), \
             patch("classes.Instagram.get_instagram_password", return_value="p"):
            from classes.Instagram import Instagram
            return Instagram("id", "nick")

    def test_empty_video_path_raises(self):
        ig = self._make_ig()
        with pytest.raises(ValueError, match="non-empty string"):
            ig.upload_reel("")

    def test_none_video_path_raises(self):
        ig = self._make_ig()
        with pytest.raises(ValueError, match="non-empty string"):
            ig.upload_reel(None)

    def test_null_byte_in_path_raises(self):
        ig = self._make_ig()
        with pytest.raises(ValueError, match="null bytes"):
            ig.upload_reel("/tmp/video\x00.mp4")

    def test_nonexistent_file_raises(self):
        ig = self._make_ig()
        with pytest.raises(ValueError, match="does not exist"):
            ig.upload_reel("/nonexistent/path/video.mp4")

    def test_unsupported_extension_raises(self, tmp_path):
        ig = self._make_ig()
        bad_file = tmp_path / "video.avi"
        bad_file.write_text("fake")
        with pytest.raises(ValueError, match="Unsupported video format"):
            ig.upload_reel(str(bad_file))

    def test_mp4_extension_accepted(self, tmp_path):
        """mp4 extension should pass validation (may fail at upload stage)."""
        ig = self._make_ig()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake video content")
        with patch.object(ig, "_get_client") as mock_client:
            mock_cl = MagicMock()
            mock_cl.clip_upload.return_value = MagicMock(pk=12345)
            mock_client.return_value = mock_cl
            with patch.object(ig, "_record_upload"), \
                 patch.object(ig, "_track_analytics"):
                result = ig.upload_reel(str(video))
        assert result is True

    def test_mov_extension_accepted(self, tmp_path):
        ig = self._make_ig()
        video = tmp_path / "test.mov"
        video.write_bytes(b"fake video content")
        with patch.object(ig, "_get_client") as mock_client:
            mock_cl = MagicMock()
            mock_cl.clip_upload.return_value = MagicMock(pk=99999)
            mock_client.return_value = mock_cl
            with patch.object(ig, "_record_upload"), \
                 patch.object(ig, "_track_analytics"):
                result = ig.upload_reel(str(video))
        assert result is True


# ---------------------------------------------------------------------------
# upload_reel caption handling tests
# ---------------------------------------------------------------------------

class TestUploadReelCaption:
    """Tests for caption truncation and handling."""

    def _make_ig(self):
        with patch("classes.Instagram.get_instagram_username", return_value="u"), \
             patch("classes.Instagram.get_instagram_password", return_value="p"):
            from classes.Instagram import Instagram
            return Instagram("id", "nick")

    def test_long_caption_truncated(self, tmp_path):
        ig = self._make_ig()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake")
        long_caption = "word " * 500  # ~2500 chars

        captured_caption = {}

        def fake_clip_upload(**kwargs):
            captured_caption["value"] = kwargs.get("caption", "")
            return MagicMock(pk=111)

        with patch.object(ig, "_get_client") as mock_client:
            mock_cl = MagicMock()
            mock_cl.clip_upload.side_effect = fake_clip_upload
            mock_client.return_value = mock_cl
            with patch.object(ig, "_record_upload"), \
                 patch.object(ig, "_track_analytics"):
                ig.upload_reel(str(video), caption=long_caption)

        assert len(captured_caption["value"]) <= 2200
        assert captured_caption["value"].endswith("...")

    def test_empty_caption_allowed(self, tmp_path):
        ig = self._make_ig()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake")

        with patch.object(ig, "_get_client") as mock_client:
            mock_cl = MagicMock()
            mock_cl.clip_upload.return_value = MagicMock(pk=222)
            mock_client.return_value = mock_cl
            with patch.object(ig, "_record_upload"), \
                 patch.object(ig, "_track_analytics"):
                result = ig.upload_reel(str(video), caption="")
        assert result is True


# ---------------------------------------------------------------------------
# upload_reel success/failure tests
# ---------------------------------------------------------------------------

class TestUploadReelResult:
    """Tests for upload success and failure paths."""

    def _make_ig(self):
        with patch("classes.Instagram.get_instagram_username", return_value="u"), \
             patch("classes.Instagram.get_instagram_password", return_value="p"):
            from classes.Instagram import Instagram
            return Instagram("id", "nick")

    def test_successful_upload_returns_true(self, tmp_path):
        ig = self._make_ig()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake")
        with patch.object(ig, "_get_client") as mock_client:
            mock_cl = MagicMock()
            mock_cl.clip_upload.return_value = MagicMock(pk=333)
            mock_client.return_value = mock_cl
            with patch.object(ig, "_record_upload"), \
                 patch.object(ig, "_track_analytics"):
                result = ig.upload_reel(str(video), caption="test")
        assert result is True

    def test_upload_returns_false_when_no_media(self, tmp_path):
        ig = self._make_ig()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake")
        with patch.object(ig, "_get_client") as mock_client:
            mock_cl = MagicMock()
            mock_cl.clip_upload.return_value = None
            mock_client.return_value = mock_cl
            result = ig.upload_reel(str(video), caption="test")
        assert result is False

    def test_upload_exception_returns_false(self, tmp_path):
        ig = self._make_ig()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake")
        with patch.object(ig, "_get_client") as mock_client:
            mock_cl = MagicMock()
            mock_cl.clip_upload.side_effect = RuntimeError("Upload error")
            mock_client.return_value = mock_cl
            result = ig.upload_reel(str(video), caption="test")
        assert result is False

    def test_import_error_propagates(self, tmp_path):
        ig = self._make_ig()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake")
        with patch.object(ig, "_get_client", side_effect=ImportError("no instagrapi")):
            with pytest.raises(ImportError):
                ig.upload_reel(str(video))

    def test_thumbnail_path_passed_when_valid(self, tmp_path):
        ig = self._make_ig()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake")
        thumb = tmp_path / "thumb.jpg"
        thumb.write_bytes(b"fake thumb")

        captured_kwargs = {}

        def fake_clip_upload(**kwargs):
            captured_kwargs.update(kwargs)
            return MagicMock(pk=444)

        with patch.object(ig, "_get_client") as mock_client:
            mock_cl = MagicMock()
            mock_cl.clip_upload.side_effect = fake_clip_upload
            mock_client.return_value = mock_cl
            with patch.object(ig, "_record_upload"), \
                 patch.object(ig, "_track_analytics"):
                ig.upload_reel(str(video), caption="test", thumbnail_path=str(thumb))
        assert "thumbnail" in captured_kwargs

    def test_invalid_thumbnail_path_ignored(self, tmp_path):
        ig = self._make_ig()
        video = tmp_path / "test.mp4"
        video.write_bytes(b"fake")

        captured_kwargs = {}

        def fake_clip_upload(**kwargs):
            captured_kwargs.update(kwargs)
            return MagicMock(pk=555)

        with patch.object(ig, "_get_client") as mock_client:
            mock_cl = MagicMock()
            mock_cl.clip_upload.side_effect = fake_clip_upload
            mock_client.return_value = mock_cl
            with patch.object(ig, "_record_upload"), \
                 patch.object(ig, "_track_analytics"):
                ig.upload_reel(str(video), caption="test", thumbnail_path="/nonexistent/thumb.jpg")
        assert "thumbnail" not in captured_kwargs


# ---------------------------------------------------------------------------
# get_reels tests
# ---------------------------------------------------------------------------

class TestGetReels:
    """Tests for get_reels() cache retrieval."""

    def _make_ig(self):
        with patch("classes.Instagram.get_instagram_username", return_value="u"), \
             patch("classes.Instagram.get_instagram_password", return_value="p"):
            from classes.Instagram import Instagram
            return Instagram("acc1", "nick")

    def test_returns_only_matching_account_reels(self):
        ig = self._make_ig()
        cache_data = {
            "reels": [
                {"account_id": "acc1", "reel_id": "r1"},
                {"account_id": "other", "reel_id": "r2"},
                {"account_id": "acc1", "reel_id": "r3"},
            ]
        }
        with patch("classes.Instagram._safe_read_cache", return_value=cache_data):
            reels = ig.get_reels()
        assert len(reels) == 2
        assert all(r["account_id"] == "acc1" for r in reels)

    def test_returns_empty_list_when_no_reels(self):
        ig = self._make_ig()
        with patch("classes.Instagram._safe_read_cache", return_value={"accounts": [], "reels": []}):
            reels = ig.get_reels()
        assert reels == []

    def test_handles_missing_reels_key(self):
        ig = self._make_ig()
        with patch("classes.Instagram._safe_read_cache", return_value={"accounts": []}):
            reels = ig.get_reels()
        assert reels == []


# ---------------------------------------------------------------------------
# _record_upload tests
# ---------------------------------------------------------------------------

class TestRecordUpload:
    """Tests for _record_upload cache writing."""

    def _make_ig(self):
        with patch("classes.Instagram.get_instagram_username", return_value="u"), \
             patch("classes.Instagram.get_instagram_password", return_value="p"):
            from classes.Instagram import Instagram
            return Instagram("acc1", "nick")

    def test_appends_reel_to_cache(self):
        ig = self._make_ig()
        existing = {"reels": []}
        written_data = {}

        def capture_write(data):
            written_data.update(data)

        with patch("classes.Instagram._safe_read_cache", return_value=existing), \
             patch("classes.Instagram._safe_write_cache", side_effect=capture_write):
            ig._record_upload("/path/video.mp4", "My caption", "reel123")

        assert len(written_data["reels"]) == 1
        assert written_data["reels"][0]["reel_id"] == "reel123"
        assert written_data["reels"][0]["account_id"] == "acc1"

    def test_truncates_caption_in_cache(self):
        ig = self._make_ig()
        written_data = {}

        def capture_write(data):
            written_data.update(data)

        with patch("classes.Instagram._safe_read_cache", return_value={"reels": []}), \
             patch("classes.Instagram._safe_write_cache", side_effect=capture_write):
            ig._record_upload("/path/video.mp4", "x" * 500, "reel456")

        assert len(written_data["reels"][0]["caption"]) <= 200

    def test_caps_cache_at_5000_entries(self):
        ig = self._make_ig()
        existing = {"reels": [{"reel_id": str(i)} for i in range(5001)]}
        written_data = {}

        def capture_write(data):
            written_data.update(data)

        with patch("classes.Instagram._safe_read_cache", return_value=existing), \
             patch("classes.Instagram._safe_write_cache", side_effect=capture_write):
            ig._record_upload("/path/video.mp4", "cap", "new_reel")

        assert len(written_data["reels"]) <= 5000


# ---------------------------------------------------------------------------
# _track_analytics tests
# ---------------------------------------------------------------------------

class TestTrackAnalytics:
    """Tests for analytics tracking in Instagram module."""

    def _make_ig(self):
        with patch("classes.Instagram.get_instagram_username", return_value="u"), \
             patch("classes.Instagram.get_instagram_password", return_value="p"):
            from classes.Instagram import Instagram
            return Instagram("acc1", "nick")

    def test_tracks_reel_uploaded_event(self):
        ig = self._make_ig()
        with patch("analytics.track_event") as mock_track:
            ig._track_analytics("reel123", "My caption")
            mock_track.assert_called_once_with(
                event_type="reel_uploaded",
                platform="instagram",
                details={
                    "reel_id": "reel123",
                    "caption_length": 10,
                    "account": "nick",
                },
            )

    def test_analytics_failure_does_not_raise(self):
        ig = self._make_ig()
        with patch("analytics.track_event", side_effect=Exception("db error")):
            # Should not raise
            ig._track_analytics("reel123", "caption")


# ---------------------------------------------------------------------------
# Context manager tests
# ---------------------------------------------------------------------------

class TestInstagramContextManager:
    """Tests for __enter__/__exit__ protocol."""

    def _make_ig(self):
        with patch("classes.Instagram.get_instagram_username", return_value="u"), \
             patch("classes.Instagram.get_instagram_password", return_value="p"):
            from classes.Instagram import Instagram
            return Instagram("id", "nick")

    def test_enter_returns_self(self):
        ig = self._make_ig()
        assert ig.__enter__() is ig

    def test_exit_clears_client(self):
        ig = self._make_ig()
        ig._client = MagicMock()
        ig.__exit__(None, None, None)
        assert ig._client is None

    def test_exit_returns_false(self):
        ig = self._make_ig()
        result = ig.__exit__(None, None, None)
        assert result is False

    def test_works_as_context_manager(self):
        ig = self._make_ig()
        ig._client = MagicMock()
        with ig as instance:
            assert instance is ig
        assert ig._client is None


# ---------------------------------------------------------------------------
# _get_client tests
# ---------------------------------------------------------------------------

class TestGetClient:
    """Tests for the _get_client authentication flow."""

    def _make_ig(self):
        with patch("classes.Instagram.get_instagram_username", return_value="u"), \
             patch("classes.Instagram.get_instagram_password", return_value="p"):
            from classes.Instagram import Instagram
            return Instagram("id", "nick")

    def test_returns_cached_client(self):
        ig = self._make_ig()
        mock_client = MagicMock()
        ig._client = mock_client
        result = ig._get_client()
        assert result is mock_client

    def test_import_error_when_instagrapi_missing(self):
        ig = self._make_ig()
        with patch("builtins.__import__", side_effect=ImportError("no instagrapi")):
            with pytest.raises(ImportError, match="instagrapi"):
                ig._get_client()

    @patch("classes.Instagram.os.path.isfile", return_value=False)
    def test_fresh_login_when_no_session(self, mock_isfile):
        ig = self._make_ig()
        mock_client_class = MagicMock()
        mock_client_instance = MagicMock()
        mock_client_class.return_value = mock_client_instance

        with patch.dict("sys.modules", {"instagrapi": MagicMock(Client=mock_client_class)}):
            with patch.object(ig, "_save_session"):
                result = ig._get_client()

        mock_client_instance.login.assert_called_once_with("u", "p")
        assert ig._client is mock_client_instance

    @patch("classes.Instagram.os.path.isfile", return_value=False)
    def test_login_failure_raises_runtime_error(self, mock_isfile):
        ig = self._make_ig()
        mock_client_class = MagicMock()
        mock_client_instance = MagicMock()
        mock_client_instance.login.side_effect = Exception("Bad credentials")
        mock_client_class.return_value = mock_client_instance

        with patch.dict("sys.modules", {"instagrapi": MagicMock(Client=mock_client_class)}):
            with pytest.raises(RuntimeError, match="Instagram login failed"):
                ig._get_client()


# ---------------------------------------------------------------------------
# _save_session tests
# ---------------------------------------------------------------------------

class TestSaveSession:
    """Tests for atomic session saving."""

    def _make_ig(self):
        with patch("classes.Instagram.get_instagram_username", return_value="u"), \
             patch("classes.Instagram.get_instagram_password", return_value="p"):
            from classes.Instagram import Instagram
            return Instagram("id", "nick")

    def test_save_session_calls_dump_settings(self, tmp_path):
        ig = self._make_ig()
        session_path = str(tmp_path / "session.json")
        mock_client = MagicMock()

        ig._save_session(mock_client, session_path)
        # dump_settings should have been called (on a temp file that gets renamed)
        assert mock_client.dump_settings.called

    def test_save_session_failure_logs_warning(self, tmp_path):
        ig = self._make_ig()
        session_path = str(tmp_path / "session.json")
        mock_client = MagicMock()
        mock_client.dump_settings.side_effect = OSError("write error")

        # Should not raise
        ig._save_session(mock_client, session_path)
