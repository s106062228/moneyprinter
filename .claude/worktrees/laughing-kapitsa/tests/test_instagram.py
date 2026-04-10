"""
Tests for src/classes/Instagram.py — Instagram Reels upload automation.

Covers:
    - Configuration helpers (get_instagram_username, get_instagram_password)
    - Cache helpers (_safe_read_cache, _safe_write_cache, _get_ig_cache_path)
    - Instagram.__init__ credential validation
    - _get_session_path sanitization and collision avoidance
    - upload_reel input validation (path, extension, caption, thumbnail null bytes)
    - upload_reel success / failure / ImportError paths
    - get_reels cache filtering
    - _record_upload atomic write and cache rotation
    - _track_analytics error handling
    - Context manager protocol (__enter__ / __exit__)
"""

import hashlib
import json
import os
import tempfile

import pytest
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import classes.Instagram as ig_module
from classes.Instagram import (
    Instagram,
    _get_ig_cache_path,
    _safe_read_cache,
    _safe_write_cache,
    get_instagram_username,
    get_instagram_password,
    _get_instagram_config,
    _MAX_CAPTION_LENGTH,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate_ig(tmp_path, monkeypatch):
    """
    Redirect ROOT_DIR so all cache / session paths land under tmp_path.
    Also clear any credential env vars so tests start from a clean slate.
    """
    monkeypatch.setattr(ig_module, "ROOT_DIR", str(tmp_path))
    monkeypatch.setattr(
        ig_module,
        "_SESSION_DIR",
        str(tmp_path / ".mp" / "ig_sessions"),
    )
    monkeypatch.delenv("IG_USERNAME", raising=False)
    monkeypatch.delenv("IG_PASSWORD", raising=False)
    yield tmp_path


@pytest.fixture
def mock_client():
    """Returns a mock instagrapi Client."""
    client = MagicMock()
    media = MagicMock()
    media.pk = "12345678"
    client.clip_upload.return_value = media
    client.get_timeline_feed.return_value = {}
    return client


@pytest.fixture
def tmp_video(tmp_path):
    """Creates a real (empty) .mp4 file and returns its path."""
    path = tmp_path / "video.mp4"
    path.write_bytes(b"\x00" * 16)
    return str(path)


def _make_ig(tmp_path, account_id="acc-001", nickname="test_acct"):
    """Helper to create an Instagram instance with patched credentials."""
    with patch.object(ig_module, "_get_instagram_config",
                      return_value={"username": "user1", "password": "pass1"}):
        return Instagram(
            account_id=account_id,
            nickname=nickname,
        )


# ---------------------------------------------------------------------------
# _get_instagram_config tests
# ---------------------------------------------------------------------------

class TestGetInstagramConfig:

    def test_returns_instagram_block(self):
        with patch("classes.Instagram._get", return_value={"username": "u", "password": "p"}):
            cfg = _get_instagram_config()
        assert cfg == {"username": "u", "password": "p"}

    def test_returns_empty_dict_when_key_missing(self):
        with patch("classes.Instagram._get", return_value={}):
            cfg = _get_instagram_config()
        assert cfg == {}

    def test_accepts_partial_config(self):
        with patch("classes.Instagram._get", return_value={"username": "only_user"}):
            cfg = _get_instagram_config()
        assert cfg.get("password") is None


# ---------------------------------------------------------------------------
# get_instagram_username / get_instagram_password tests
# ---------------------------------------------------------------------------

class TestCredentialHelpers:

    def test_username_from_config(self):
        with patch.object(ig_module, "_get_instagram_config",
                          return_value={"username": "cfg_user", "password": ""}):
            assert get_instagram_username() == "cfg_user"

    def test_username_env_fallback(self, monkeypatch):
        monkeypatch.setenv("IG_USERNAME", "env_user")
        with patch.object(ig_module, "_get_instagram_config",
                          return_value={"username": "", "password": ""}):
            assert get_instagram_username() == "env_user"

    def test_username_empty_when_neither_set(self):
        with patch.object(ig_module, "_get_instagram_config",
                          return_value={"username": "", "password": ""}):
            assert get_instagram_username() == ""

    def test_username_config_takes_precedence_over_env(self, monkeypatch):
        monkeypatch.setenv("IG_USERNAME", "env_user")
        with patch.object(ig_module, "_get_instagram_config",
                          return_value={"username": "cfg_user", "password": ""}):
            assert get_instagram_username() == "cfg_user"

    def test_password_from_config(self):
        with patch.object(ig_module, "_get_instagram_config",
                          return_value={"username": "", "password": "cfg_pass"}):
            assert get_instagram_password() == "cfg_pass"

    def test_password_env_fallback(self, monkeypatch):
        monkeypatch.setenv("IG_PASSWORD", "env_pass")
        with patch.object(ig_module, "_get_instagram_config",
                          return_value={"username": "", "password": ""}):
            assert get_instagram_password() == "env_pass"

    def test_password_empty_when_neither_set(self):
        with patch.object(ig_module, "_get_instagram_config",
                          return_value={"username": "", "password": ""}):
            assert get_instagram_password() == ""


# ---------------------------------------------------------------------------
# Cache helper tests
# ---------------------------------------------------------------------------

class TestCacheHelpers:

    def test_get_ig_cache_path_ends_with_instagram_json(self):
        path = _get_ig_cache_path()
        assert path.endswith("instagram.json")

    def test_safe_read_cache_returns_default_when_missing(self, tmp_path):
        result = _safe_read_cache()
        assert result == {"accounts": [], "reels": []}

    def test_safe_read_cache_returns_default_on_invalid_json(self, tmp_path):
        cache_file = tmp_path / ".mp" / "instagram.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text("not valid json {{")
        result = _safe_read_cache()
        assert result == {"accounts": [], "reels": []}

    def test_safe_read_cache_returns_data(self, tmp_path):
        cache_file = tmp_path / ".mp" / "instagram.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        data = {"accounts": [{"id": "a1"}], "reels": []}
        cache_file.write_text(json.dumps(data))
        result = _safe_read_cache()
        assert result["accounts"][0]["id"] == "a1"

    def test_safe_read_cache_returns_default_on_non_dict(self, tmp_path):
        cache_file = tmp_path / ".mp" / "instagram.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps([1, 2, 3]))
        result = _safe_read_cache()
        assert result == {"accounts": [], "reels": []}

    def test_safe_write_cache_creates_file(self, tmp_path):
        data = {"accounts": [], "reels": [{"reel_id": "r1"}]}
        _safe_write_cache(data)
        cache_file = tmp_path / ".mp" / "instagram.json"
        assert cache_file.exists()
        written = json.loads(cache_file.read_text())
        assert written["reels"][0]["reel_id"] == "r1"

    def test_safe_write_cache_is_atomic(self, tmp_path):
        """Write should not leave temp files behind."""
        _safe_write_cache({"accounts": [], "reels": []})
        mp_dir = tmp_path / ".mp"
        tmp_files = list(mp_dir.glob("*.tmp"))
        assert tmp_files == []


# ---------------------------------------------------------------------------
# Instagram.__init__ tests
# ---------------------------------------------------------------------------

class TestInstagramInit:

    def test_init_stores_credentials(self):
        ig = Instagram(
            account_id="abc-1",
            nickname="acct",
            username="explicit_user",
            password="explicit_pass",
        )
        assert ig.account_id == "abc-1"
        assert ig.nickname == "acct"
        assert ig.username == "explicit_user"
        assert ig.password == "explicit_pass"
        assert ig._client is None

    def test_init_falls_back_to_config(self):
        with patch.object(ig_module, "_get_instagram_config",
                          return_value={"username": "cfg_u", "password": "cfg_p"}):
            ig = Instagram(account_id="x", nickname="n")
        assert ig.username == "cfg_u"
        assert ig.password == "cfg_p"

    def test_init_raises_when_no_username(self):
        with patch.object(ig_module, "_get_instagram_config",
                          return_value={"username": "", "password": "pass"}):
            with pytest.raises(ValueError, match="credentials not configured"):
                Instagram(account_id="x", nickname="n")

    def test_init_raises_when_no_password(self):
        with patch.object(ig_module, "_get_instagram_config",
                          return_value={"username": "user", "password": ""}):
            with pytest.raises(ValueError, match="credentials not configured"):
                Instagram(account_id="x", nickname="n")

    def test_init_raises_when_neither_set(self):
        with patch.object(ig_module, "_get_instagram_config",
                          return_value={"username": "", "password": ""}):
            with pytest.raises(ValueError):
                Instagram(account_id="x", nickname="n")


# ---------------------------------------------------------------------------
# _get_session_path tests
# ---------------------------------------------------------------------------

class TestGetSessionPath:

    def test_path_ends_with_account_id_session(self):
        ig = _make_ig(None)
        path = ig._get_session_path()
        assert "acc-001_session.json" in path

    def test_special_chars_stripped_from_account_id(self):
        ig = Instagram(
            account_id="foo/bar!@#",
            nickname="n",
            username="u",
            password="p",
        )
        path = ig._get_session_path()
        assert "/" not in os.path.basename(path)
        assert "!" not in os.path.basename(path)

    def test_long_account_id_capped_at_50_chars(self):
        long_id = "a" * 100
        ig = Instagram(account_id=long_id, nickname="n", username="u", password="p")
        basename = os.path.basename(ig._get_session_path())
        # basename is "<safe_id[:50]>_session.json"
        safe_part = basename.replace("_session.json", "")
        assert len(safe_part) <= 50

    def test_all_special_chars_account_id_uses_hash_fallback(self):
        """account_id with no alphanumeric chars must not collide with 'default'."""
        id1 = "@@@"
        id2 = "!!!"
        ig1 = Instagram(account_id=id1, nickname="n", username="u", password="p")
        ig2 = Instagram(account_id=id2, nickname="n", username="u", password="p")
        path1 = ig1._get_session_path()
        path2 = ig2._get_session_path()
        # Paths must differ because hash fallback uses SHA-256 of the raw id
        assert path1 != path2


# ---------------------------------------------------------------------------
# upload_reel validation tests
# ---------------------------------------------------------------------------

class TestUploadReelValidation:

    def test_empty_video_path_raises(self):
        ig = _make_ig(None)
        with pytest.raises(ValueError, match="non-empty string"):
            ig.upload_reel(video_path="")

    def test_none_video_path_raises(self):
        ig = _make_ig(None)
        with pytest.raises(ValueError):
            ig.upload_reel(video_path=None)

    def test_null_byte_in_video_path_raises(self):
        ig = _make_ig(None)
        with pytest.raises(ValueError, match="null bytes"):
            ig.upload_reel(video_path="/tmp/video\x00.mp4")

    def test_nonexistent_video_path_raises(self):
        ig = _make_ig(None)
        with pytest.raises(ValueError, match="does not exist"):
            ig.upload_reel(video_path="/nonexistent/video.mp4")

    def test_unsupported_extension_avi_raises(self, tmp_path):
        path = tmp_path / "video.avi"
        path.write_bytes(b"\x00")
        ig = _make_ig(None)
        with pytest.raises(ValueError, match="Unsupported video format"):
            ig.upload_reel(video_path=str(path))

    def test_unsupported_extension_txt_raises(self, tmp_path):
        path = tmp_path / "file.txt"
        path.write_bytes(b"hello")
        ig = _make_ig(None)
        with pytest.raises(ValueError, match="Unsupported video format"):
            ig.upload_reel(video_path=str(path))

    def test_caption_truncated_to_max_length(self, tmp_video, mock_client):
        ig = _make_ig(None)
        long_caption = "word " * 1000  # > 2200 chars
        with patch.object(ig, "_get_client", return_value=mock_client):
            with patch.object(ig, "_record_upload"):
                with patch.object(ig, "_track_analytics"):
                    ig.upload_reel(video_path=tmp_video, caption=long_caption)
        # caption passed to clip_upload should not exceed limit
        call_args = mock_client.clip_upload.call_args
        caption_arg = call_args[1].get("caption", call_args[0][1] if len(call_args[0]) > 1 else "")
        assert len(caption_arg) <= _MAX_CAPTION_LENGTH

    def test_mov_extension_accepted(self, tmp_path, mock_client):
        path = tmp_path / "video.mov"
        path.write_bytes(b"\x00" * 16)
        ig = _make_ig(None)
        with patch.object(ig, "_get_client", return_value=mock_client):
            with patch.object(ig, "_record_upload"):
                with patch.object(ig, "_track_analytics"):
                    result = ig.upload_reel(video_path=str(path))
        assert result is True

    def test_thumbnail_null_byte_raises(self, tmp_video):
        ig = _make_ig(None)
        with patch.object(ig, "_get_client", return_value=MagicMock()):
            with pytest.raises(ValueError, match="null bytes"):
                ig.upload_reel(
                    video_path=tmp_video,
                    thumbnail_path="/tmp/thumb\x00.jpg",
                )

    def test_thumbnail_non_string_raises(self, tmp_video):
        ig = _make_ig(None)
        with patch.object(ig, "_get_client", return_value=MagicMock()):
            with pytest.raises(ValueError, match="null bytes or is not a string"):
                ig.upload_reel(video_path=tmp_video, thumbnail_path=12345)


# ---------------------------------------------------------------------------
# upload_reel success / failure tests
# ---------------------------------------------------------------------------

class TestUploadReelSuccess:

    def test_returns_true_on_success(self, tmp_video, mock_client):
        ig = _make_ig(None)
        with patch.object(ig, "_get_client", return_value=mock_client):
            with patch.object(ig, "_record_upload") as rec:
                with patch.object(ig, "_track_analytics") as trk:
                    result = ig.upload_reel(video_path=tmp_video, caption="Test caption")
        assert result is True
        rec.assert_called_once()
        trk.assert_called_once()

    def test_records_reel_id_on_success(self, tmp_video, mock_client):
        ig = _make_ig(None)
        with patch.object(ig, "_get_client", return_value=mock_client):
            with patch.object(ig, "_record_upload") as rec:
                with patch.object(ig, "_track_analytics"):
                    ig.upload_reel(video_path=tmp_video)
        args = rec.call_args[0]
        assert args[2] == "12345678"  # reel_id from mock media.pk

    def test_thumbnail_passed_to_clip_upload_when_valid(self, tmp_path, mock_client):
        video = tmp_path / "v.mp4"
        video.write_bytes(b"\x00" * 16)
        thumb = tmp_path / "thumb.jpg"
        thumb.write_bytes(b"\xff\xd8\xff")

        ig = _make_ig(None)
        with patch.object(ig, "_get_client", return_value=mock_client):
            with patch.object(ig, "_record_upload"):
                with patch.object(ig, "_track_analytics"):
                    ig.upload_reel(video_path=str(video), thumbnail_path=str(thumb))
        call_kwargs = mock_client.clip_upload.call_args[1]
        assert call_kwargs.get("thumbnail") == str(thumb)

    def test_returns_false_when_media_is_none(self, tmp_video):
        client = MagicMock()
        client.clip_upload.return_value = None
        ig = _make_ig(None)
        with patch.object(ig, "_get_client", return_value=client):
            result = ig.upload_reel(video_path=tmp_video)
        assert result is False

    def test_returns_false_on_upload_exception(self, tmp_video):
        client = MagicMock()
        client.clip_upload.side_effect = RuntimeError("network error")
        ig = _make_ig(None)
        with patch.object(ig, "_get_client", return_value=client):
            result = ig.upload_reel(video_path=tmp_video)
        assert result is False

    def test_import_error_reraises(self, tmp_video):
        ig = _make_ig(None)
        with patch.object(ig, "_get_client", side_effect=ImportError("no instagrapi")):
            with pytest.raises(ImportError):
                ig.upload_reel(video_path=tmp_video)


# ---------------------------------------------------------------------------
# get_reels tests
# ---------------------------------------------------------------------------

class TestGetReels:

    def test_returns_empty_list_when_no_reels(self, tmp_path):
        ig = _make_ig(tmp_path)
        assert ig.get_reels() == []

    def test_returns_reels_for_this_account(self, tmp_path):
        ig = _make_ig(tmp_path)
        data = {
            "reels": [
                {"account_id": "acc-001", "reel_id": "r1", "caption": "hi", "date": "2026-01-01"},
                {"account_id": "other-acc", "reel_id": "r2", "caption": "bye", "date": "2026-01-02"},
            ]
        }
        _safe_write_cache(data)
        reels = ig.get_reels()
        assert len(reels) == 1
        assert reels[0]["reel_id"] == "r1"

    def test_filters_out_other_accounts_reels(self, tmp_path):
        ig = _make_ig(tmp_path)
        data = {"reels": [{"account_id": "stranger", "reel_id": "rx"}]}
        _safe_write_cache(data)
        assert ig.get_reels() == []


# ---------------------------------------------------------------------------
# _record_upload tests
# ---------------------------------------------------------------------------

class TestRecordUpload:

    def test_appends_reel_to_cache(self, tmp_path):
        ig = _make_ig(tmp_path)
        ig._record_upload("/tmp/v.mp4", "Caption text", "reel-99")
        data = _safe_read_cache()
        assert len(data["reels"]) == 1
        assert data["reels"][0]["reel_id"] == "reel-99"

    def test_caption_truncated_to_200_chars(self, tmp_path):
        ig = _make_ig(tmp_path)
        long_caption = "x" * 500
        ig._record_upload("/tmp/v.mp4", long_caption, "reel-1")
        data = _safe_read_cache()
        assert len(data["reels"][0]["caption"]) <= 200

    def test_reel_id_capped_at_64_chars(self, tmp_path):
        ig = _make_ig(tmp_path)
        long_id = "r" * 200
        ig._record_upload("/tmp/v.mp4", "caption", long_id)
        data = _safe_read_cache()
        assert len(data["reels"][0]["reel_id"]) <= 64

    def test_cache_rotated_when_exceeds_5000(self, tmp_path):
        ig = _make_ig(tmp_path)
        # Seed cache with 5000 entries
        entries = [
            {"account_id": "acc-001", "reel_id": str(i), "caption": "", "date": "2026-01-01"}
            for i in range(5000)
        ]
        _safe_write_cache({"reels": entries})
        ig._record_upload("/tmp/v.mp4", "new caption", "new-reel")
        data = _safe_read_cache()
        assert len(data["reels"]) == 5000
        # The oldest entry (index 0) should have been evicted
        assert data["reels"][-1]["reel_id"] == "new-reel"

    def test_includes_account_id_and_date(self, tmp_path):
        ig = _make_ig(tmp_path)
        ig._record_upload("/tmp/v.mp4", "hello", "reel-x")
        data = _safe_read_cache()
        entry = data["reels"][0]
        assert entry["account_id"] == "acc-001"
        assert "date" in entry


# ---------------------------------------------------------------------------
# _track_analytics tests
# ---------------------------------------------------------------------------

class TestTrackAnalytics:

    def test_calls_track_event(self, tmp_path):
        ig = _make_ig(tmp_path)
        mock_track = MagicMock()
        with patch("classes.Instagram.track_event", mock_track, create=True):
            with patch("builtins.__import__", side_effect=lambda name, *a, **k: (
                type("mod", (), {"track_event": mock_track}) if name == "analytics" else __import__(name, *a, **k)
            )):
                ig._track_analytics("reel-1", "caption")

    def test_swallows_analytics_errors(self, tmp_path):
        ig = _make_ig(tmp_path)
        # Should not raise even if analytics import fails
        with patch("builtins.__import__", side_effect=ImportError("no analytics")):
            ig._track_analytics("reel-1", "caption")  # must not raise


# ---------------------------------------------------------------------------
# Context manager tests
# ---------------------------------------------------------------------------

class TestContextManager:

    def test_enter_returns_self(self):
        ig = _make_ig(None)
        assert ig.__enter__() is ig

    def test_exit_resets_client(self, mock_client):
        ig = _make_ig(None)
        ig._client = mock_client  # Simulate an open session
        ig.__exit__(None, None, None)
        assert ig._client is None

    def test_exit_returns_false(self):
        ig = _make_ig(None)
        result = ig.__exit__(None, None, None)
        assert result is False

    def test_context_manager_cleans_up(self, mock_client):
        with patch.object(ig_module, "_get_instagram_config",
                          return_value={"username": "u", "password": "p"}):
            with Instagram(account_id="a", nickname="n") as ig:
                ig._client = mock_client
        assert ig._client is None
