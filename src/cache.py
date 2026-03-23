import os
import json
import tempfile

from typing import List
from config import ROOT_DIR

def get_cache_path() -> str:
    """
    Gets the path to the cache file.

    Returns:
        path (str): The path to the cache folder
    """
    return os.path.join(ROOT_DIR, '.mp')

def get_afm_cache_path() -> str:
    """
    Gets the path to the Affiliate Marketing cache file.

    Returns:
        path (str): The path to the AFM cache folder
    """
    return os.path.join(get_cache_path(), 'afm.json')

def get_twitter_cache_path() -> str:
    """
    Gets the path to the Twitter cache file.

    Returns:
        path (str): The path to the Twitter cache folder
    """
    return os.path.join(get_cache_path(), 'twitter.json')

def get_youtube_cache_path() -> str:
    """
    Gets the path to the YouTube cache file.

    Returns:
        path (str): The path to the YouTube cache folder
    """
    return os.path.join(get_cache_path(), 'youtube.json')

def get_provider_cache_path(provider: str) -> str:
    """
    Gets the cache path for a supported account provider.

    Args:
        provider (str): The provider name ("twitter" or "youtube")

    Returns:
        path (str): The provider-specific cache path

    Raises:
        ValueError: If the provider is unsupported
    """
    if provider == "twitter":
        return get_twitter_cache_path()
    if provider == "youtube":
        return get_youtube_cache_path()

    raise ValueError(f"Unsupported provider '{provider}'. Expected 'twitter' or 'youtube'.")


def _safe_write_json(path: str, data: dict) -> None:
    """
    Atomically writes JSON data to a file using a temporary file + rename.
    This prevents TOCTOU race conditions and partial writes.

    Args:
        path: The target file path.
        data: The dict to serialize as JSON.
    """
    dir_name = os.path.dirname(path)
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=4)
        os.replace(tmp_path, path)
    except Exception:
        # Clean up the temp file if something goes wrong
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _safe_read_json(path: str, default: dict = None) -> dict:
    """
    Reads JSON from a file, returning a default if the file doesn't exist
    or contains invalid JSON. Avoids TOCTOU by using try/except rather
    than os.path.exists() checks.

    Args:
        path: The file path to read.
        default: Default value if file doesn't exist or is invalid.

    Returns:
        The parsed JSON dict.
    """
    if default is None:
        default = {}
    try:
        with open(path, 'r') as f:
            parsed = json.load(f)
            return parsed if parsed is not None else default
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        return default


def get_accounts(provider: str) -> List[dict]:
    """
    Gets the accounts from the cache.

    Args:
        provider (str): The provider to get the accounts for

    Returns:
        account (List[dict]): The accounts
    """
    cache_path = get_provider_cache_path(provider)
    data = _safe_read_json(cache_path, {"accounts": []})

    if 'accounts' not in data:
        return []

    return data['accounts']

def add_account(provider: str, account: dict) -> None:
    """
    Adds an account to the cache.

    Args:
        provider (str): The provider to add the account to ("twitter" or "youtube")
        account (dict): The account to add

    Returns:
        None
    """
    cache_path = get_provider_cache_path(provider)

    # Get the current accounts
    accounts = get_accounts(provider)

    # Add the new account
    accounts.append(account)

    # Write atomically
    _safe_write_json(cache_path, {"accounts": accounts})

def remove_account(provider: str, account_id: str) -> None:
    """
    Removes an account from the cache.

    Args:
        provider (str): The provider to remove the account from ("twitter" or "youtube")
        account_id (str): The ID of the account to remove

    Returns:
        None
    """
    # Get the current accounts
    accounts = get_accounts(provider)

    # Remove the account
    accounts = [account for account in accounts if account['id'] != account_id]

    # Write atomically
    cache_path = get_provider_cache_path(provider)
    _safe_write_json(cache_path, {"accounts": accounts})

def get_products() -> List[dict]:
    """
    Gets the products from the cache.

    Returns:
        products (List[dict]): The products
    """
    data = _safe_read_json(get_afm_cache_path(), {"products": []})
    return data.get("products", [])

def add_product(product: dict) -> None:
    """
    Adds a product to the cache.

    Args:
        product (dict): The product to add

    Returns:
        None
    """
    # Get the current products
    products = get_products()

    # Add the new product
    products.append(product)

    # Write atomically
    _safe_write_json(get_afm_cache_path(), {"products": products})

def get_results_cache_path() -> str:
    """
    Gets the path to the results cache file.

    Returns:
        path (str): The path to the results cache folder
    """
    return os.path.join(get_cache_path(), 'scraper_results.csv')
