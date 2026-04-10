# RUN THIS N AMOUNT OF TIMES
import sys

from status import *
from cache import get_accounts
from config import get_verbose
from classes.Tts import TTS
from classes.Twitter import Twitter
from classes.YouTube import YouTube
from llm_provider import select_model

def main():
    """Main function to post content to Twitter or upload videos to YouTube.

    This function determines its operation based on command-line arguments:
    - If the purpose is "twitter", it initializes a Twitter account and posts a message.
    - If the purpose is "youtube", it initializes a YouTube account, generates a video with TTS, and uploads it.

    Command-line arguments:
        sys.argv[1]: A string indicating the purpose, either "twitter" or "youtube".
        sys.argv[2]: A string representing the account UUID.
        sys.argv[3]: The Ollama model name.

    Args:
        None. The function uses command-line arguments accessed via sys.argv.

    Returns:
        None."""
    if len(sys.argv) < 3:
        error("Usage: cron.py <twitter|youtube> <account_uuid> [model_name]")
        sys.exit(1)

    purpose = str(sys.argv[1]).strip()
    account_id = str(sys.argv[2]).strip()
    model = str(sys.argv[3]).strip() if len(sys.argv) > 3 else None

    # Validate purpose to prevent unexpected behavior
    if purpose not in ("twitter", "youtube"):
        error(f"Invalid purpose: {purpose}. Expected 'twitter' or 'youtube'.")
        sys.exit(1)

    # Validate account_id is a plausible UUID (basic check)
    if not account_id or len(account_id) < 8:
        error("Account UUID appears invalid.")
        sys.exit(1)

    if model:
        select_model(model)
    else:
        error("No Ollama model specified. Pass model name as third argument.")
        sys.exit(1)

    verbose = get_verbose()

    if purpose == "twitter":
        accounts = get_accounts("twitter")

        if not account_id:
            error("Account UUID cannot be empty.")

        for acc in accounts:
            if acc["id"] == account_id:
                if verbose:
                    info("Initializing Twitter...")
                twitter = Twitter(
                    acc["id"],
                    acc["nickname"],
                    acc["firefox_profile"],
                    acc["topic"]
                )
                twitter.post()
                if verbose:
                    success("Done posting.")
                break
    elif purpose == "youtube":
        tts = TTS()

        accounts = get_accounts("youtube")

        if not account_id:
            error("Account UUID cannot be empty.")

        for acc in accounts:
            if acc["id"] == account_id:
                if verbose:
                    info("Initializing YouTube...")
                youtube = YouTube(
                    acc["id"],
                    acc["nickname"],
                    acc["firefox_profile"],
                    acc["niche"],
                    acc["language"]
                )
                youtube.generate_video(tts)
                youtube.upload_video()
                if verbose:
                    success("Uploaded Short.")
                break
    else:
        error("Invalid Purpose, exiting...")
        sys.exit(1)

if __name__ == "__main__":
    main()
