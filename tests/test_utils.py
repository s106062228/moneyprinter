"""
Tests for src/utils.py — utility functions.
"""

import os
import pytest
from unittest.mock import patch, MagicMock

import utils


class TestBuildUrl:
    """Tests for build_url()."""

    def test_valid_video_id(self):
        """Constructs correct YouTube URL."""
        result = utils.build_url("dQw4w9WgXcQ")
        assert result == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_empty_video_id(self):
        """Handles empty video ID."""
        result = utils.build_url("")
        assert result == "https://www.youtube.com/watch?v="


class TestRemTempFiles:
    """Tests for rem_temp_files()."""

    def test_removes_non_json_files(self, tmp_path):
        """Removes non-JSON files from .mp directory."""
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()

        # Create test files
        (mp_dir / "temp_video.mp4").write_text("video data")
        (mp_dir / "temp_audio.wav").write_text("audio data")
        (mp_dir / "analytics.json").write_text("{}")

        with patch.object(utils, "ROOT_DIR", str(tmp_path)):
            utils.rem_temp_files()

        remaining = os.listdir(str(mp_dir))
        assert "analytics.json" in remaining
        assert "temp_video.mp4" not in remaining
        assert "temp_audio.wav" not in remaining

    def test_preserves_json_files(self, tmp_path):
        """Keeps all .json files in .mp directory."""
        mp_dir = tmp_path / ".mp"
        mp_dir.mkdir()

        (mp_dir / "twitter.json").write_text("{}")
        (mp_dir / "youtube.json").write_text("{}")

        with patch.object(utils, "ROOT_DIR", str(tmp_path)):
            utils.rem_temp_files()

        remaining = os.listdir(str(mp_dir))
        assert "twitter.json" in remaining
        assert "youtube.json" in remaining


class TestChooseRandomSong:
    """Tests for choose_random_song()."""

    def test_returns_song_path(self, tmp_path):
        """Returns a valid path to an audio file."""
        songs_dir = tmp_path / "Songs"
        songs_dir.mkdir()
        (songs_dir / "beat.mp3").write_text("fake audio")
        (songs_dir / "groove.wav").write_text("fake audio")

        with patch.object(utils, "ROOT_DIR", str(tmp_path)):
            result = utils.choose_random_song()

        assert os.path.basename(result) in ["beat.mp3", "groove.wav"]

    def test_raises_when_no_songs(self, tmp_path):
        """Raises RuntimeError when Songs directory is empty."""
        songs_dir = tmp_path / "Songs"
        songs_dir.mkdir()

        with patch.object(utils, "ROOT_DIR", str(tmp_path)):
            with pytest.raises(RuntimeError, match="No audio files"):
                utils.choose_random_song()

    def test_ignores_non_audio_files(self, tmp_path):
        """Only considers audio file extensions."""
        songs_dir = tmp_path / "Songs"
        songs_dir.mkdir()
        (songs_dir / "readme.txt").write_text("not audio")
        (songs_dir / "song.mp3").write_text("fake audio")

        with patch.object(utils, "ROOT_DIR", str(tmp_path)):
            result = utils.choose_random_song()

        assert result.endswith(".mp3")
