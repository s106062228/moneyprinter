import os
import time
import json
import tempfile

from cache import *
from config import *
from status import *
from typing import List, Optional
from datetime import datetime
from termcolor import colored
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


class TikTok:
    """
    Class for TikTok video upload automation.

    Automates the process of uploading short-form videos to TikTok
    via the web interface using Selenium browser automation.
    """

    TIKTOK_UPLOAD_URL = "https://www.tiktok.com/upload"
    TIKTOK_CREATOR_URL = "https://www.tiktok.com/creator#/upload"

    def __init__(
        self,
        account_uuid: str,
        account_nickname: str,
        fp_profile_path: str,
        niche: str,
    ) -> None:
        """
        Constructor for TikTok class.

        Args:
            account_uuid: Unique identifier for the TikTok account.
            account_nickname: Display name for the account.
            fp_profile_path: Path to Firefox profile logged into TikTok.
            niche: Content niche for the account.
        """
        self._account_uuid = account_uuid
        self._account_nickname = account_nickname
        self._fp_profile_path = fp_profile_path
        self._niche = niche

        self.options = Options()

        if get_headless():
            self.options.add_argument("--headless")

        if not os.path.isdir(self._fp_profile_path):
            raise ValueError(
                f"Firefox profile path does not exist or is not a directory: "
                f"{self._fp_profile_path}"
            )

        self.options.add_argument("-profile")
        self.options.add_argument(self._fp_profile_path)

        self.service = Service(GeckoDriverManager().install())
        self.browser = webdriver.Firefox(
            service=self.service, options=self.options
        )
        self.wait = WebDriverWait(self.browser, 30)

    @property
    def niche(self) -> str:
        return self._niche

    def get_tiktok_cache_path(self) -> str:
        """Returns path to TikTok cache file."""
        return os.path.join(get_cache_path(), "tiktok.json")

    def _safe_read_cache(self) -> dict:
        """Reads TikTok cache using try/except (TOCTOU-safe)."""
        cache_path = self.get_tiktok_cache_path()
        try:
            with open(cache_path, "r") as f:
                data = json.load(f)
                return data if data is not None else {"accounts": []}
        except (FileNotFoundError, json.JSONDecodeError, IOError):
            return {"accounts": []}

    def _safe_write_cache(self, data: dict) -> None:
        """Atomically writes TikTok cache using tempfile + os.replace."""
        cache_path = self.get_tiktok_cache_path()
        dir_name = os.path.dirname(cache_path)
        os.makedirs(dir_name, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=4)
            os.replace(tmp_path, cache_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def get_videos(self) -> List[dict]:
        """Gets uploaded videos from cache."""
        data = self._safe_read_cache()

        for account in data.get("accounts", []):
            if account.get("id") == self._account_uuid:
                return account.get("videos", [])

        return []

    def add_video(self, video: dict) -> None:
        """Adds a video record to cache."""
        data = self._safe_read_cache()

        account_found = False
        for account in data.get("accounts", []):
            if account.get("id") == self._account_uuid:
                account.setdefault("videos", []).append(video)
                account_found = True
                break

        if not account_found:
            data["accounts"].append(
                {
                    "id": self._account_uuid,
                    "nickname": self._account_nickname,
                    "niche": self._niche,
                    "videos": [video],
                }
            )

        self._safe_write_cache(data)

    def upload_video(
        self,
        video_path: str,
        title: str,
        description: Optional[str] = None,
    ) -> bool:
        """
        Uploads a video to TikTok via the web creator portal.

        Args:
            video_path: Absolute path to the video file.
            title: Title/caption for the TikTok video.
            description: Optional description text.

        Returns:
            True if upload appeared successful, False otherwise.
        """
        if not os.path.isfile(video_path):
            error(f"Video file not found: {video_path}")
            return False

        try:
            driver = self.browser
            verbose = get_verbose()

            if verbose:
                info(" => Navigating to TikTok upload page...")

            driver.get(self.TIKTOK_CREATOR_URL)
            time.sleep(5)

            # Look for the file input element
            file_input_selectors = [
                (By.CSS_SELECTOR, "input[type='file']"),
                (By.XPATH, "//input[@accept='video/*']"),
                (By.XPATH, "//input[@type='file']"),
            ]

            file_input = None
            for selector in file_input_selectors:
                try:
                    file_input = self.wait.until(
                        EC.presence_of_element_located(selector)
                    )
                    break
                except Exception:
                    continue

            if file_input is None:
                error("Could not find file input on TikTok upload page.")
                return False

            file_input.send_keys(os.path.abspath(video_path))

            if verbose:
                info(" => Video file selected, waiting for processing...")

            time.sleep(10)

            # Set caption/title
            caption_selectors = [
                (
                    By.CSS_SELECTOR,
                    "div[data-e2e='caption-editor'] .public-DraftEditor-content",
                ),
                (By.CSS_SELECTOR, "div[contenteditable='true']"),
                (By.XPATH, "//div[@contenteditable='true']"),
            ]

            caption_el = None
            for selector in caption_selectors:
                try:
                    caption_el = self.wait.until(
                        EC.element_to_be_clickable(selector)
                    )
                    break
                except Exception:
                    continue

            if caption_el:
                caption_el.click()
                time.sleep(0.5)
                caption_el.clear()
                caption_text = title
                if description:
                    caption_text += "\n\n" + description
                caption_el.send_keys(caption_text)

                if verbose:
                    info(" => Caption set successfully.")
            else:
                warning("Could not find caption editor. Continuing without caption...")

            time.sleep(3)

            # Click the post button
            post_button_selectors = [
                (By.CSS_SELECTOR, "button[data-e2e='post-button']"),
                (By.XPATH, "//button[contains(text(), 'Post')]"),
                (By.XPATH, "//div[contains(@class, 'btn-post')]//button"),
            ]

            post_button = None
            for selector in post_button_selectors:
                try:
                    post_button = self.wait.until(
                        EC.element_to_be_clickable(selector)
                    )
                    break
                except Exception:
                    continue

            if post_button is None:
                error("Could not find the Post button on TikTok upload page.")
                return False

            post_button.click()

            if verbose:
                info(" => Post button clicked, waiting for upload...")

            time.sleep(10)

            # Record the upload
            self.add_video(
                {
                    "title": title,
                    "description": description or "",
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "status": "uploaded",
                }
            )

            success(f" => Successfully uploaded video to TikTok: {title}")
            return True

        except Exception as e:
            error(f"TikTok upload failed: {e}")
            return False
        finally:
            try:
                self.browser.quit()
            except Exception:
                pass

    def quit(self) -> None:
        """Closes the browser."""
        try:
            self.browser.quit()
        except Exception:
            pass
