import os
import io
import re
import csv
import time
import glob
import shlex
import zipfile
import yagmail
import requests
import subprocess
import platform
from urllib.parse import urlparse

from cache import *
from status import *
from config import *
from validation import validate_url

# Rate limit: minimum seconds between outreach emails
_EMAIL_SEND_DELAY = 2


class Outreach:
    """
    Class that houses the methods to reach out to businesses.
    """

    def __init__(self) -> None:
        """
        Constructor for the Outreach class.

        Returns:
            None
        """
        # Check if go is installed (use subprocess instead of os.system for safety)
        try:
            subprocess.run(["go", "version"], capture_output=True, check=False)
            self.go_installed = True
        except FileNotFoundError:
            self.go_installed = False

        # Set niche
        self.niche = get_google_maps_scraper_niche()

        # Set email credentials
        self.email_creds = get_email_credentials()

    def _find_scraper_dir(self) -> str:
        candidates = sorted(glob.glob("google-maps-scraper-*"))
        for candidate in candidates:
            if os.path.isdir(candidate) and os.path.exists(
                os.path.join(candidate, "go.mod")
            ):
                return candidate
        return ""

    def is_go_installed(self) -> bool:
        """
        Check if go is installed.

        Returns:
            bool: True if go is installed, False otherwise.
        """
        try:
            subprocess.run(["go", "version"], capture_output=True, check=False)
            return True
        except (FileNotFoundError, OSError):
            return False

    def unzip_file(self, zip_link: str) -> None:
        """
        Unzip the file.

        Args:
            zip_link (str): The link to the zip file.

        Returns:
            None
        """
        if self._find_scraper_dir():
            info("=> Scraper already unzipped. Skipping unzip.")
            return

        r = requests.get(zip_link, timeout=60)
        r.raise_for_status()

        # Validate content looks like a ZIP before processing
        content = r.content
        if not content[:4] == b'PK\x03\x04' and not content[:4] == b'PK\x05\x06':
            raise ValueError("Downloaded content is not a valid ZIP file.")

        z = zipfile.ZipFile(io.BytesIO(content))
        target_dir = os.path.abspath(os.getcwd())
        for member in z.namelist():
            # Resolve the full extraction path and verify it stays within target
            member_path = os.path.normpath(os.path.join(target_dir, member))
            if not member_path.startswith(target_dir):
                warning(f"Skipping path traversal attempt in archive: {member}")
                continue
            if ".." in member or member.startswith("/"):
                warning(f"Skipping suspicious path in archive: {member}")
                continue
            z.extract(member)

    def build_scraper(self) -> None:
        """
        Build the scraper.

        Returns:
            None
        """
        binary_name = (
            "google-maps-scraper.exe"
            if platform.system() == "Windows"
            else "google-maps-scraper"
        )
        if os.path.exists(binary_name):
            print(colored("=> Scraper already built. Skipping build.", "blue"))
            return

        scraper_dir = self._find_scraper_dir()
        if not scraper_dir:
            raise FileNotFoundError(
                "Could not locate extracted google-maps-scraper directory."
            )

        subprocess.run(["go", "mod", "download"], cwd=scraper_dir, check=True)
        subprocess.run(["go", "build"], cwd=scraper_dir, check=True)

        built_binary = os.path.join(scraper_dir, binary_name)
        if not os.path.exists(built_binary):
            raise FileNotFoundError(f"Expected built scraper binary at: {built_binary}")

        os.replace(built_binary, binary_name)

    def run_scraper_with_args_for_30_seconds(self, args: str, timeout=300) -> None:
        """
        Run the scraper with the specified arguments for 30 seconds.

        Args:
            args (str): The arguments to run the scraper with.
            timeout (int): The time to run the scraper for.

        Returns:
            None
        """
        info(" => Running scraper...")
        binary_name = (
            "google-maps-scraper.exe"
            if platform.system() == "Windows"
            else "google-maps-scraper"
        )
        command = [os.path.join(os.getcwd(), binary_name)] + shlex.split(args)
        try:
            scraper_process = subprocess.run(command, timeout=float(timeout))

            if scraper_process.returncode == 0:
                print(colored("=> Scraper finished successfully.", "green"))
            else:
                print(colored("=> Scraper finished with an error.", "red"))
        except subprocess.TimeoutExpired:
            print(colored("=> Scraper timed out.", "red"))
        except Exception as e:
            print(colored("An error occurred while running the scraper.", "red"))
            # Avoid leaking sensitive paths or system details in error output
            print(colored(f"Error type: {type(e).__name__}", "red"))

    def get_items_from_file(self, file_name: str) -> list:
        """
        Read and return items from a file.

        Args:
            file_name (str): The name of the file to read from.

        Returns:
            list: The items from the file.
        """
        # Read and return items from a file
        with open(file_name, "r", errors="ignore") as f:
            items = f.readlines()
            items = [item.strip() for item in items[1:]]
            return items

    def set_email_for_website(self, index: int, website: str, output_file: str):
        """Extracts an email address from a website and updates a CSV file with it.

        This method sends a GET request to the specified website, searches for the
        first email address in the HTML content, and appends it to the specified
        row in a CSV file. If no email address is found, no changes are made to
        the CSV file.

        Args:
            index (int): The row index in the CSV file where the email should be appended.
            website (str): The URL of the website to extract the email address from.
            output_file (str): The path to the CSV file to update with the extracted email."""
        # Extract and set an email for a website
        email = ""

        # Validate URL before making request (prevents SSRF)
        try:
            validate_url(website, allowed_schemes=("http", "https"))
            parsed = urlparse(website)
            # Block requests to private/internal IPs
            if parsed.hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
                warning(f" => Skipping internal URL: {website}")
                return
        except ValueError:
            warning(f" => Invalid URL: {website}")
            return

        r = requests.get(website, timeout=30)
        if r.status_code == 200:
            # Define a regular expression pattern to match email addresses
            email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"

            # Find all email addresses in the HTML string
            email_addresses = re.findall(email_pattern, r.text)

            email = email_addresses[0] if len(email_addresses) > 0 else ""

        if email:
            print(f"=> Setting email for website {website}")
            with open(output_file, "r", newline="", errors="ignore") as csvfile:
                csvreader = csv.reader(csvfile)
                items = list(csvreader)
                if 0 <= index < len(items):
                    items[index].append(email)
                else:
                    warning(f" => Index {index} out of range for CSV file. Skipping.")
                    return

            # Atomic write: write to temp file then replace
            dir_name = os.path.dirname(os.path.abspath(output_file))
            import tempfile
            fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".csv.tmp")
            try:
                with os.fdopen(fd, "w", newline="", errors="ignore") as csvfile:
                    csvwriter = csv.writer(csvfile)
                    csvwriter.writerows(items)
                os.replace(tmp_path, output_file)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

    def start(self) -> None:
        """
        Start the outreach process.

        Returns:
            None
        """
        # Check if go is installed
        if not self.is_go_installed():
            error("Go is not installed. Please install go and try again.")
            return

        # Unzip the scraper
        self.unzip_file(get_google_maps_scraper_zip_url())

        # Build the scraper
        self.build_scraper()

        # Write the niche to a temp file (avoid polluting cwd with arbitrary data)
        niche_path = os.path.join(os.getcwd(), "niche.txt")
        with open(niche_path, "w") as f:
            f.write(self.niche[:500])  # Limit length to prevent abuse

        output_path = get_results_cache_path()
        message_subject = get_outreach_message_subject()
        message_body = get_outreach_message_body_file()

        # Validate message body file path to prevent arbitrary file read
        if message_body:
            abs_body = os.path.abspath(message_body)
            abs_root = os.path.abspath(os.path.join(os.getcwd(), ".."))
            if not abs_body.startswith(abs_root):
                error(" => Message body file path is outside project directory. Aborting.")
                os.remove(niche_path)
                return
            if not os.path.isfile(abs_body):
                error(" => Message body file not found. Check outreach_message_body_file in config.")
                os.remove(niche_path)
                return

        # Run
        self.run_scraper_with_args_for_30_seconds(
            f'-input niche.txt -results "{output_path}"', timeout=get_scraper_timeout()
        )

        if not os.path.exists(output_path):
            error(
                " => Scraper output not found. Check scraper logs and configuration."
            )
            os.remove(niche_path)
            return

        # Get the items from the file
        items = self.get_items_from_file(output_path)
        success(f" => Scraped {len(items)} items.")

        # Remove the niche file
        os.remove("niche.txt")

        time.sleep(2)

        # Create a yagmail SMTP client outside the loop
        yag = yagmail.SMTP(
            user=self.email_creds["username"],
            password=self.email_creds["password"],
            host=self.email_creds["smtp_server"],
            port=self.email_creds["smtp_port"],
        )

        # Get the email for each business
        for index, item in enumerate(items, start=1):
            try:
                # Parse CSV fields properly (handles quoted commas)
                parsed_fields = list(csv.reader([item]))
                if not parsed_fields or not parsed_fields[0]:
                    warning(f" => Empty row at index {index}. Skipping...")
                    continue
                fields = parsed_fields[0]

                # Extract website URL from fields
                website_candidates = [f for f in fields if f.strip().startswith("http")]
                website = website_candidates[0].strip() if website_candidates else ""
                if website != "":
                    # Validate URL before making request (SSRF protection)
                    try:
                        validate_url(website, allowed_schemes=("http", "https"))
                        parsed_ws = urlparse(website)
                        if parsed_ws.hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
                            warning(f" => Skipping internal URL: {website}")
                            continue
                    except ValueError:
                        warning(f" => Invalid URL in scraper output: {website}")
                        continue

                    test_r = requests.get(website, timeout=30)
                    if test_r.status_code == 200:
                        self.set_email_for_website(index, website, output_path)

                        # Send emails using the existing SMTP connection
                        receiver_email = fields[-1].strip() if fields else ""

                        # Validate email format before sending
                        import re as _re
                        _email_re = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
                        if not _re.match(_email_re, receiver_email):
                            warning(f" => No email provided. Skipping...")
                            continue

                        company_name = fields[0].strip() if fields else ""
                        subject = message_subject.replace(
                            "{{COMPANY_NAME}}", company_name
                        )
                        with open(message_body, "r") as body_file:
                            body = body_file.read().replace(
                                "{{COMPANY_NAME}}", company_name
                            )

                        info(f" => Sending email to {receiver_email}...")

                        yag.send(
                            to=receiver_email,
                            subject=subject,
                            contents=body,
                        )

                        success(f" => Sent email to {receiver_email}")

                        # Rate limit: pause between email sends
                        time.sleep(_EMAIL_SEND_DELAY)
                    else:
                        warning(f" => Website {website} is invalid. Skipping...")
            except Exception as err:
                # Avoid leaking sensitive info in error output
                error(f" => Error processing item: {type(err).__name__}")
                continue
