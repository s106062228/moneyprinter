"""
Tests for Twitter.py and YouTube.py atomic cache operations.

Tests cover:
- _safe_read_cache() — handles missing files, existing files, corrupt JSON
- _safe_write_cache() — writes atomically with correct data
- get_posts/get_videos() — returns empty list when account missing, returns data when found
- add_post/add_video() — adds to existing account, handles missing cache
"""

import os
import json
import sys
import pytest
from unittest.mock import patch, MagicMock, Mock
from pathlib import Path

import cache as cache_module


@pytest.fixture(autouse=True)
def isolate_cache(tmp_path):
    """Redirect cache to use temp directory."""
    mp_dir = str(tmp_path / ".mp")
    os.makedirs(mp_dir, exist_ok=True)
    with patch.object(cache_module, "ROOT_DIR", str(tmp_path)):
        yield tmp_path


def create_twitter_instance(account_uuid, account_nickname, topic):
    """
    Create a Twitter instance without starting Firefox.
    Uses __new__ to bypass __init__ which requires Selenium.
    Mocks out all heavy dependencies.
    """
    # Mock out heavy dependencies before importing
    with patch.dict(sys.modules, {
        'ollama': MagicMock(),
        'llm_provider': MagicMock(),
        'selenium_firefox': MagicMock(),
        'selenium': MagicMock(),
        'selenium.webdriver': MagicMock(),
        'selenium.webdriver.firefox': MagicMock(),
        'selenium.webdriver.firefox.service': MagicMock(),
        'selenium.webdriver.firefox.options': MagicMock(),
        'selenium.webdriver.common.by': MagicMock(),
        'selenium.webdriver.support': MagicMock(),
        'selenium.webdriver.support.ui': MagicMock(),
        'selenium.webdriver.support.expected_conditions': MagicMock(),
        'webdriver_manager': MagicMock(),
        'webdriver_manager.firefox': MagicMock(),
        'status': MagicMock(),
    }):
        from classes.Twitter import Twitter

        # Create instance without calling __init__
        instance = Twitter.__new__(Twitter)
        instance.account_uuid = account_uuid
        instance.account_nickname = account_nickname
        instance.topic = topic

        return instance


def create_youtube_instance(account_uuid, account_nickname, niche, language):
    """
    Create a YouTube instance without starting Firefox.
    Uses __new__ to bypass __init__ which requires Selenium.
    Mocks out all heavy dependencies.
    """
    # Mock out heavy dependencies before importing
    with patch.dict(sys.modules, {
        'assemblyai': MagicMock(),
        'assemblyai.aai': MagicMock(),
        'requests': MagicMock(),
        'soundfile': MagicMock(),
        'numpy': MagicMock(),
        'pydub': MagicMock(),
        'pydub.AudioSegment': MagicMock(),
        'kittentts': MagicMock(),
        'ollama': MagicMock(),
        'llm_provider': MagicMock(),
        'selenium_firefox': MagicMock(),
        'selenium': MagicMock(),
        'selenium.webdriver': MagicMock(),
        'selenium.webdriver.firefox': MagicMock(),
        'selenium.webdriver.firefox.service': MagicMock(),
        'selenium.webdriver.firefox.options': MagicMock(),
        'selenium.webdriver.common.by': MagicMock(),
        'webdriver_manager': MagicMock(),
        'webdriver_manager.firefox': MagicMock(),
        'moviepy': MagicMock(),
        'moviepy.editor': MagicMock(),
        'moviepy.video': MagicMock(),
        'moviepy.video.fx': MagicMock(),
        'moviepy.video.fx.all': MagicMock(),
        'moviepy.video.tools': MagicMock(),
        'moviepy.video.tools.subtitles': MagicMock(),
        'moviepy.config': MagicMock(),
        'faster_whisper': MagicMock(),
        'status': MagicMock(),
        'constants': MagicMock(),
        'utils': MagicMock(),
    }):
        from classes.YouTube import YouTube

        # Create instance without calling __init__
        instance = YouTube.__new__(YouTube)
        instance._account_uuid = account_uuid
        instance._account_nickname = account_nickname
        instance._niche = niche
        instance._language = language
        instance.images = []

        return instance


class TestTwitterSafeReadCache:
    """Tests for Twitter._safe_read_cache()."""

    def test_returns_default_when_file_missing(self, isolate_cache):
        """Returns default empty structure when cache file doesn't exist."""
        twitter = create_twitter_instance("uuid-1", "account1", "tech")
        result = twitter._safe_read_cache()

        assert result == {"accounts": []}

    def test_returns_data_when_file_exists(self, isolate_cache):
        """Returns parsed data when cache file exists."""
        # Create cache file with data
        cache_data = {
            "accounts": [
                {"id": "uuid-1", "nickname": "account1", "topic": "tech", "posts": []}
            ]
        }
        cache_path = cache_module.get_twitter_cache_path()
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(cache_data, f)

        twitter = create_twitter_instance("uuid-1", "account1", "tech")
        result = twitter._safe_read_cache()

        assert result == cache_data

    def test_handles_corrupt_json(self, isolate_cache):
        """Returns default when JSON is corrupt."""
        cache_path = cache_module.get_twitter_cache_path()
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as f:
            f.write("{invalid json}")

        twitter = create_twitter_instance("uuid-1", "account1", "tech")
        result = twitter._safe_read_cache()

        assert result == {"accounts": []}

    def test_handles_null_json(self, isolate_cache):
        """Returns default when JSON is null."""
        cache_path = cache_module.get_twitter_cache_path()
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(None, f)

        twitter = create_twitter_instance("uuid-1", "account1", "tech")
        result = twitter._safe_read_cache()

        assert result == {"accounts": []}


class TestTwitterSafeWriteCache:
    """Tests for Twitter._safe_write_cache()."""

    def test_writes_atomically(self, isolate_cache):
        """Writes data atomically to cache file."""
        twitter = create_twitter_instance("uuid-1", "account1", "tech")
        cache_data = {
            "accounts": [
                {"id": "uuid-1", "nickname": "account1", "topic": "tech", "posts": []}
            ]
        }

        twitter._safe_write_cache(cache_data)

        # Verify file exists and contains correct data
        cache_path = cache_module.get_twitter_cache_path()
        assert os.path.exists(cache_path)

        with open(cache_path, "r") as f:
            written_data = json.load(f)

        assert written_data == cache_data

    def test_file_contains_correct_data(self, isolate_cache):
        """Verifies written file contains exactly the provided data."""
        twitter = create_twitter_instance("uuid-1", "account1", "tech")
        cache_data = {
            "accounts": [
                {
                    "id": "uuid-1",
                    "nickname": "account1",
                    "topic": "tech",
                    "posts": [
                        {"content": "Hello world", "date": "12/24/2023, 10:30:00"}
                    ]
                },
                {
                    "id": "uuid-2",
                    "nickname": "account2",
                    "topic": "science",
                    "posts": []
                }
            ]
        }

        twitter._safe_write_cache(cache_data)

        cache_path = cache_module.get_twitter_cache_path()
        with open(cache_path, "r") as f:
            written_data = json.load(f)

        assert written_data == cache_data
        assert len(written_data["accounts"]) == 2

    def test_creates_directory_if_missing(self, isolate_cache):
        """Creates cache directory if it doesn't exist."""
        # Remove the .mp directory
        mp_dir = os.path.join(str(isolate_cache), ".mp")
        if os.path.exists(mp_dir):
            import shutil
            shutil.rmtree(mp_dir)

        twitter = create_twitter_instance("uuid-1", "account1", "tech")
        cache_data = {"accounts": []}

        twitter._safe_write_cache(cache_data)

        cache_path = cache_module.get_twitter_cache_path()
        assert os.path.exists(cache_path)


class TestTwitterGetPosts:
    """Tests for Twitter.get_posts()."""

    def test_returns_empty_list_when_no_account_found(self, isolate_cache):
        """Returns empty list when account UUID not in cache."""
        # Create cache with different account
        cache_data = {
            "accounts": [
                {"id": "other-uuid", "nickname": "other", "topic": "science", "posts": []}
            ]
        }
        cache_path = cache_module.get_twitter_cache_path()
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(cache_data, f)

        twitter = create_twitter_instance("my-uuid", "myaccount", "tech")
        result = twitter.get_posts()

        assert result == []

    def test_returns_posts_when_account_exists(self, isolate_cache):
        """Returns posts list when account is found."""
        cache_data = {
            "accounts": [
                {
                    "id": "my-uuid",
                    "nickname": "myaccount",
                    "topic": "tech",
                    "posts": [
                        {"content": "First post", "date": "12/24/2023, 10:00:00"},
                        {"content": "Second post", "date": "12/24/2023, 11:00:00"}
                    ]
                }
            ]
        }
        cache_path = cache_module.get_twitter_cache_path()
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(cache_data, f)

        twitter = create_twitter_instance("my-uuid", "myaccount", "tech")
        result = twitter.get_posts()

        assert len(result) == 2
        assert result[0]["content"] == "First post"
        assert result[1]["content"] == "Second post"

    def test_returns_empty_list_when_cache_missing(self, isolate_cache):
        """Returns empty list when cache file doesn't exist."""
        twitter = create_twitter_instance("my-uuid", "myaccount", "tech")
        result = twitter.get_posts()

        assert result == []

    def test_returns_empty_when_posts_field_missing(self, isolate_cache):
        """Returns empty list when posts field is missing from account."""
        cache_data = {
            "accounts": [
                {"id": "my-uuid", "nickname": "myaccount", "topic": "tech"}
            ]
        }
        cache_path = cache_module.get_twitter_cache_path()
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(cache_data, f)

        twitter = create_twitter_instance("my-uuid", "myaccount", "tech")
        result = twitter.get_posts()

        assert result == []


class TestTwitterAddPost:
    """Tests for Twitter.add_post()."""

    def test_adds_post_to_existing_account(self, isolate_cache):
        """Adds post to existing account in cache."""
        cache_data = {
            "accounts": [
                {
                    "id": "my-uuid",
                    "nickname": "myaccount",
                    "topic": "tech",
                    "posts": [
                        {"content": "First post", "date": "12/24/2023, 10:00:00"}
                    ]
                }
            ]
        }
        cache_path = cache_module.get_twitter_cache_path()
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(cache_data, f)

        twitter = create_twitter_instance("my-uuid", "myaccount", "tech")
        new_post = {"content": "Second post", "date": "12/24/2023, 11:00:00"}
        twitter.add_post(new_post)

        result = twitter.get_posts()
        assert len(result) == 2
        assert result[1]["content"] == "Second post"

    def test_adds_post_creates_account_if_missing(self, isolate_cache):
        """Creates account if it doesn't exist when adding post."""
        twitter = create_twitter_instance("new-uuid", "newaccount", "science")
        post = {"content": "New post", "date": "12/24/2023, 12:00:00"}

        twitter.add_post(post)

        result = twitter.get_posts()
        assert len(result) == 1
        assert result[0]["content"] == "New post"

    def test_handles_missing_cache_on_add(self, isolate_cache):
        """Handles adding post when cache file doesn't exist."""
        twitter = create_twitter_instance("uuid-1", "account1", "tech")
        post = {"content": "First post", "date": "12/24/2023, 10:00:00"}

        twitter.add_post(post)

        cache_path = cache_module.get_twitter_cache_path()
        assert os.path.exists(cache_path)

        result = twitter.get_posts()
        assert len(result) == 1
        assert result[0]["content"] == "First post"

    def test_preserves_other_accounts_when_adding_post(self, isolate_cache):
        """Preserves other accounts when adding post to one account."""
        cache_data = {
            "accounts": [
                {"id": "uuid-1", "nickname": "account1", "topic": "tech", "posts": []},
                {"id": "uuid-2", "nickname": "account2", "topic": "science", "posts": []}
            ]
        }
        cache_path = cache_module.get_twitter_cache_path()
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(cache_data, f)

        twitter = create_twitter_instance("uuid-1", "account1", "tech")
        post = {"content": "New post", "date": "12/24/2023, 10:00:00"}
        twitter.add_post(post)

        data = twitter._safe_read_cache()
        assert len(data["accounts"]) == 2
        assert data["accounts"][0]["posts"] == [post]
        assert data["accounts"][1]["posts"] == []


class TestYouTubeSafeReadCache:
    """Tests for YouTube._safe_read_cache()."""

    def test_returns_default_when_file_missing(self, isolate_cache):
        """Returns default empty structure when cache file doesn't exist."""
        youtube = create_youtube_instance("uuid-1", "channel1", "tech", "en")
        result = youtube._safe_read_cache()

        assert result == {"accounts": []}

    def test_returns_data_when_file_exists(self, isolate_cache):
        """Returns parsed data when cache file exists."""
        cache_data = {
            "accounts": [
                {
                    "id": "uuid-1",
                    "nickname": "channel1",
                    "niche": "tech",
                    "language": "en",
                    "videos": []
                }
            ]
        }
        cache_path = cache_module.get_youtube_cache_path()
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(cache_data, f)

        youtube = create_youtube_instance("uuid-1", "channel1", "tech", "en")
        result = youtube._safe_read_cache()

        assert result == cache_data

    def test_handles_corrupt_json(self, isolate_cache):
        """Returns default when JSON is corrupt."""
        cache_path = cache_module.get_youtube_cache_path()
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as f:
            f.write("{invalid json content}")

        youtube = create_youtube_instance("uuid-1", "channel1", "tech", "en")
        result = youtube._safe_read_cache()

        assert result == {"accounts": []}

    def test_handles_null_json(self, isolate_cache):
        """Returns default when JSON is null."""
        cache_path = cache_module.get_youtube_cache_path()
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(None, f)

        youtube = create_youtube_instance("uuid-1", "channel1", "tech", "en")
        result = youtube._safe_read_cache()

        assert result == {"accounts": []}


class TestYouTubeSafeWriteCache:
    """Tests for YouTube._safe_write_cache()."""

    def test_writes_atomically(self, isolate_cache):
        """Writes data atomically to cache file."""
        youtube = create_youtube_instance("uuid-1", "channel1", "tech", "en")
        cache_data = {
            "accounts": [
                {
                    "id": "uuid-1",
                    "nickname": "channel1",
                    "niche": "tech",
                    "language": "en",
                    "videos": []
                }
            ]
        }

        youtube._safe_write_cache(cache_data)

        cache_path = cache_module.get_youtube_cache_path()
        assert os.path.exists(cache_path)

        with open(cache_path, "r") as f:
            written_data = json.load(f)

        assert written_data == cache_data

    def test_file_contains_correct_data(self, isolate_cache):
        """Verifies written file contains exactly the provided data."""
        youtube = create_youtube_instance("uuid-1", "channel1", "tech", "en")
        cache_data = {
            "accounts": [
                {
                    "id": "uuid-1",
                    "nickname": "channel1",
                    "niche": "tech",
                    "language": "en",
                    "videos": [
                        {
                            "title": "My Video",
                            "description": "A great video",
                            "url": "https://youtube.com/watch?v=abc",
                            "date": "2023-12-24 10:30:00"
                        }
                    ]
                }
            ]
        }

        youtube._safe_write_cache(cache_data)

        cache_path = cache_module.get_youtube_cache_path()
        with open(cache_path, "r") as f:
            written_data = json.load(f)

        assert written_data == cache_data
        assert len(written_data["accounts"]) == 1
        assert len(written_data["accounts"][0]["videos"]) == 1

    def test_creates_directory_if_missing(self, isolate_cache):
        """Creates cache directory if it doesn't exist."""
        # Remove the .mp directory
        mp_dir = os.path.join(str(isolate_cache), ".mp")
        if os.path.exists(mp_dir):
            import shutil
            shutil.rmtree(mp_dir)

        youtube = create_youtube_instance("uuid-1", "channel1", "tech", "en")
        cache_data = {"accounts": []}

        youtube._safe_write_cache(cache_data)

        cache_path = cache_module.get_youtube_cache_path()
        assert os.path.exists(cache_path)


class TestYouTubeGetVideos:
    """Tests for YouTube.get_videos()."""

    def test_returns_empty_list_when_no_account_found(self, isolate_cache):
        """Returns empty list when account UUID not in cache."""
        cache_data = {
            "accounts": [
                {
                    "id": "other-uuid",
                    "nickname": "other",
                    "niche": "science",
                    "language": "en",
                    "videos": []
                }
            ]
        }
        cache_path = cache_module.get_youtube_cache_path()
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(cache_data, f)

        youtube = create_youtube_instance("my-uuid", "mychannel", "tech", "en")
        result = youtube.get_videos()

        assert result == []

    def test_returns_videos_when_account_exists(self, isolate_cache):
        """Returns videos list when account is found."""
        cache_data = {
            "accounts": [
                {
                    "id": "my-uuid",
                    "nickname": "mychannel",
                    "niche": "tech",
                    "language": "en",
                    "videos": [
                        {
                            "title": "Video 1",
                            "description": "First video",
                            "url": "https://youtube.com/watch?v=1",
                            "date": "2023-12-24 10:00:00"
                        },
                        {
                            "title": "Video 2",
                            "description": "Second video",
                            "url": "https://youtube.com/watch?v=2",
                            "date": "2023-12-24 11:00:00"
                        }
                    ]
                }
            ]
        }
        cache_path = cache_module.get_youtube_cache_path()
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(cache_data, f)

        youtube = create_youtube_instance("my-uuid", "mychannel", "tech", "en")
        result = youtube.get_videos()

        assert len(result) == 2
        assert result[0]["title"] == "Video 1"
        assert result[1]["title"] == "Video 2"

    def test_returns_empty_list_when_cache_missing(self, isolate_cache):
        """Returns empty list when cache file doesn't exist."""
        youtube = create_youtube_instance("my-uuid", "mychannel", "tech", "en")
        result = youtube.get_videos()

        assert result == []

    def test_returns_empty_when_videos_field_missing(self, isolate_cache):
        """Returns empty list when videos field is missing from account."""
        cache_data = {
            "accounts": [
                {
                    "id": "my-uuid",
                    "nickname": "mychannel",
                    "niche": "tech",
                    "language": "en"
                }
            ]
        }
        cache_path = cache_module.get_youtube_cache_path()
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(cache_data, f)

        youtube = create_youtube_instance("my-uuid", "mychannel", "tech", "en")
        result = youtube.get_videos()

        assert result == []


class TestYouTubeAddVideo:
    """Tests for YouTube.add_video()."""

    def test_adds_video_to_existing_account(self, isolate_cache):
        """Adds video to existing account in cache."""
        cache_data = {
            "accounts": [
                {
                    "id": "my-uuid",
                    "nickname": "mychannel",
                    "niche": "tech",
                    "language": "en",
                    "videos": [
                        {
                            "title": "First Video",
                            "description": "desc",
                            "url": "https://youtube.com/watch?v=1",
                            "date": "2023-12-24 10:00:00"
                        }
                    ]
                }
            ]
        }
        cache_path = cache_module.get_youtube_cache_path()
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(cache_data, f)

        youtube = create_youtube_instance("my-uuid", "mychannel", "tech", "en")
        new_video = {
            "title": "Second Video",
            "description": "Another great video",
            "url": "https://youtube.com/watch?v=2",
            "date": "2023-12-24 11:00:00"
        }
        youtube.add_video(new_video)

        result = youtube.get_videos()
        assert len(result) == 2
        assert result[1]["title"] == "Second Video"

    def test_adds_video_creates_account_if_missing(self, isolate_cache):
        """Creates account if it doesn't exist when adding video."""
        youtube = create_youtube_instance("new-uuid", "newchannel", "science", "fr")
        video = {
            "title": "New Video",
            "description": "New video",
            "url": "https://youtube.com/watch?v=new",
            "date": "2023-12-24 12:00:00"
        }

        youtube.add_video(video)

        result = youtube.get_videos()
        assert len(result) == 1
        assert result[0]["title"] == "New Video"

    def test_handles_missing_cache_on_add(self, isolate_cache):
        """Handles adding video when cache file doesn't exist."""
        youtube = create_youtube_instance("uuid-1", "channel1", "tech", "en")
        video = {
            "title": "First Video",
            "description": "First",
            "url": "https://youtube.com/watch?v=1",
            "date": "2023-12-24 10:00:00"
        }

        youtube.add_video(video)

        cache_path = cache_module.get_youtube_cache_path()
        assert os.path.exists(cache_path)

        result = youtube.get_videos()
        assert len(result) == 1
        assert result[0]["title"] == "First Video"

    def test_preserves_other_accounts_when_adding_video(self, isolate_cache):
        """Preserves other accounts when adding video to one account."""
        cache_data = {
            "accounts": [
                {
                    "id": "uuid-1",
                    "nickname": "channel1",
                    "niche": "tech",
                    "language": "en",
                    "videos": []
                },
                {
                    "id": "uuid-2",
                    "nickname": "channel2",
                    "niche": "science",
                    "language": "fr",
                    "videos": []
                }
            ]
        }
        cache_path = cache_module.get_youtube_cache_path()
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(cache_data, f)

        youtube = create_youtube_instance("uuid-1", "channel1", "tech", "en")
        video = {
            "title": "New Video",
            "description": "New",
            "url": "https://youtube.com/watch?v=new",
            "date": "2023-12-24 10:00:00"
        }
        youtube.add_video(video)

        data = youtube._safe_read_cache()
        assert len(data["accounts"]) == 2
        assert len(data["accounts"][0]["videos"]) == 1
        assert len(data["accounts"][1]["videos"]) == 0
