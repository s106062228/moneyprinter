import re
import sys
import time
import os
import json
import tempfile

from cache import *
from config import *
from status import *
from llm_provider import generate_text
from typing import List, Optional
from datetime import datetime
from termcolor import colored
from selenium_firefox import *
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


class Twitter:
    """
    Class for the Bot, that grows a Twitter account.
    """

    def __init__(
        self, account_uuid: str, account_nickname: str, fp_profile_path: str, topic: str
    ) -> None:
        """
        Initializes the Twitter Bot.

        Args:
            account_uuid (str): The account UUID
            account_nickname (str): The account nickname
            fp_profile_path (str): The path to the Firefox profile

        Returns:
            None
        """
        self.account_uuid: str = account_uuid
        self.account_nickname: str = account_nickname
        self.fp_profile_path: str = fp_profile_path
        self.topic: str = topic

        # Initialize the Firefox profile
        self.options: Options = Options()

        # Set headless state of browser
        if get_headless():
            self.options.add_argument("--headless")

        if not os.path.isdir(fp_profile_path):
            raise ValueError(
                f"Firefox profile path does not exist or is not a directory: {fp_profile_path}"
            )

        # Set the profile path
        self.options.add_argument("-profile")
        self.options.add_argument(fp_profile_path)

        # Set the service
        self.service: Service = Service(GeckoDriverManager().install())

        # Initialize the browser
        self.browser: webdriver.Firefox = webdriver.Firefox(
            service=self.service, options=self.options
        )
        self.wait: WebDriverWait = WebDriverWait(self.browser, 30)

    def __enter__(self):
        """Context manager entry — returns self."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit — ensures browser is closed."""
        try:
            self.browser.quit()
        except Exception:
            pass
        return False

    def post(self, text: Optional[str] = None) -> None:
        """
        Starts the Twitter Bot.

        Args:
            text (str): The text to post

        Returns:
            None
        """
        bot: webdriver.Firefox = self.browser
        verbose: bool = get_verbose()

        bot.get("https://x.com/compose/post")

        post_content: str = text if text is not None else self.generate_post()
        now: datetime = datetime.now()

        print(colored(" => Posting to Twitter:", "blue"), post_content[:30] + "...")
        body = post_content

        text_box = None
        text_box_selectors = [
            (By.CSS_SELECTOR, "div[data-testid='tweetTextarea_0'][role='textbox']"),
            (By.XPATH, "//div[@data-testid='tweetTextarea_0']//div[@role='textbox']"),
            (By.XPATH, "//div[@role='textbox']"),
        ]

        for selector in text_box_selectors:
            try:
                text_box = self.wait.until(EC.element_to_be_clickable(selector))
                text_box.click()
                text_box.send_keys(body)
                break
            except Exception:
                continue

        if text_box is None:
            raise RuntimeError(
                "Could not find tweet text box. Ensure you are logged into X in this Firefox profile."
            )


        post_button = None
        post_button_selectors = [
            (By.XPATH, "//button[@data-testid='tweetButtonInline']"),
            (By.XPATH, "//button[@data-testid='tweetButton']"),
            (By.XPATH, "//span[text()='Post']/ancestor::button"),
        ]

        for selector in post_button_selectors:
            try:
                post_button = self.wait.until(EC.element_to_be_clickable(selector))
                post_button.click()
                break
            except Exception:
                continue

        if post_button is None:
            raise RuntimeError("Could not find the Post button on X compose screen.")

        if verbose:
            print(colored(" => Pressed [ENTER] Button on Twitter..", "blue"))
        time.sleep(2)

        # Add the post to the cache
        self.add_post({"content": body, "date": now.strftime("%m/%d/%Y, %H:%M:%S")})

        success("Posted to Twitter successfully!")

    def _safe_read_cache(self) -> dict:
        """
        Reads Twitter cache using try/except (TOCTOU-safe).

        Returns:
            dict: The parsed cache or default empty structure.
        """
        cache_path = get_twitter_cache_path()
        try:
            with open(cache_path, "r") as f:
                data = json.load(f)
                return data if data is not None else {"accounts": []}
        except (FileNotFoundError, json.JSONDecodeError, IOError):
            return {"accounts": []}

    def _safe_write_cache(self, data: dict) -> None:
        """
        Atomically writes Twitter cache using tempfile + os.replace.

        Args:
            data (dict): The data to write.
        """
        cache_path = get_twitter_cache_path()
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

    def get_posts(self) -> List[dict]:
        """
        Gets the posts from the cache.

        Returns:
            posts (List[dict]): The posts
        """
        data = self._safe_read_cache()

        # Find our account
        for account in data.get("accounts", []):
            if account.get("id") == self.account_uuid:
                posts = account.get("posts", [])
                return posts if posts is not None else []

        return []

    def add_post(self, post: dict) -> None:
        """
        Adds a post to the cache.

        Args:
            post (dict): The post to add

        Returns:
            None
        """
        data = self._safe_read_cache()

        account_found = False
        for account in data.get("accounts", []):
            if account.get("id") == self.account_uuid:
                account.setdefault("posts", []).append(post)
                account_found = True
                break

        if not account_found:
            data["accounts"].append(
                {
                    "id": self.account_uuid,
                    "nickname": self.account_nickname,
                    "topic": self.topic,
                    "posts": [post],
                }
            )

        self._safe_write_cache(data)

    def generate_post(self) -> str:
        """
        Generates a post for the Twitter account based on the topic.

        Returns:
            post (str): The post
        """
        completion = generate_text(
            f"Generate a Twitter post about: {self.topic} in {get_twitter_language()}. "
            "The Limit is 2 sentences. Choose a specific sub-topic of the provided topic."
        )

        if get_verbose():
            info("Generating a post...")

        if completion is None:
            error("Failed to generate a post. Please try again.")
            sys.exit(1)

        # Apply Regex to remove all *
        completion = re.sub(r"\*", "", completion).replace('"', "")

        if get_verbose():
            info(f"Length of post: {len(completion)}")
        if len(completion) >= 260:
            return completion[:257].rsplit(" ", 1)[0] + "..."

        return completion
