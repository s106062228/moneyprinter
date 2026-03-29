import os
import json
import tempfile

from typing import List
from config import ROOT_DIR

# ---------------------------------------------------------------------------
# Encryption at rest (optional, keyed from MONEYPRINTER_CACHE_KEY env var)
# ---------------------------------------------------------------------------

_fernet_instance = None  # module-level cache
_fernet_checked = False  # avoid repeated lookups

def _get_fernet():
    """Return a Fernet instance if MONEYPRINTER_CACHE_KEY is set, else None.

    The Fernet instance is cached at module level for performance.
    Returns None if the env var is unset or cryptography is not installed.
    """
    global _fernet_instance, _fernet_checked
    if _fernet_checked:
        return _fernet_instance
    _fernet_checked = True
    key = os.environ.get("MONEYPRINTER_CACHE_KEY")
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet
        _fernet_instance = Fernet(key.encode() if isinstance(key, str) else key)
        return _fernet_instance
    except ImportError:
        return None


def _encrypt_bytes(data: bytes) -> bytes:
    """Encrypt data if a Fernet key is configured, otherwise return as-is."""
    f = _get_fernet()
    if f is None:
        return data
    return f.encrypt(data)


def _decrypt_bytes(data: bytes) -> bytes:
    """Decrypt data if a Fernet key is configured.

    If the data looks encrypted (starts with 'gAAAAA') but no key is set,
    raises ValueError with a clear message.
    """
    f = _get_fernet()
    # Check if data looks like a Fernet token
    is_encrypted = data.startswith(b"gAAAAA")
    if is_encrypted and f is None:
        raise ValueError(
            "Cache file appears encrypted but MONEYPRINTER_CACHE_KEY is not set. "
            "Set the environment variable to decrypt."
        )
    if f is None:
        return data
    if not is_encrypted:
        return data  # plaintext data, no decryption needed
    return f.decrypt(data)


def _reset_fernet():
    """Reset the cached Fernet instance. Used for testing."""
    global _fernet_instance, _fernet_checked
    _fernet_instance = None
    _fernet_checked = False


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

def get_instagram_cache_path() -> str:
    """
    Gets the path to the Instagram cache file.

    Returns:
        path (str): The path to the Instagram cache folder
    """
    return os.path.join(get_cache_path(), 'instagram.json')

def get_provider_cache_path(provider: str) -> str:
    """
    Gets the cache path for a supported account provider.

    Args:
        provider (str): The provider name ("twitter", "youtube", or "instagram")

    Returns:
        path (str): The provider-specific cache path

    Raises:
        ValueError: If the provider is unsupported
    """
    if provider == "twitter":
        return get_twitter_cache_path()
    if provider == "youtube":
        return get_youtube_cache_path()
    if provider == "instagram":
        return get_instagram_cache_path()

    raise ValueError(f"Unsupported provider '{provider}'. Expected 'twitter', 'youtube', or 'instagram'.")


def _safe_write_json(path: str, data: dict) -> None:
    """
    Atomically writes JSON data to a file using a temporary file + rename.
    This prevents TOCTOU race conditions and partial writes.
    If MONEYPRINTER_CACHE_KEY is set, the file is Fernet-encrypted at rest.

    Args:
        path: The target file path.
        data: The dict to serialize as JSON.
    """
    dir_name = os.path.dirname(path)
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        json_bytes = json.dumps(data, indent=4).encode("utf-8")
        encrypted = _encrypt_bytes(json_bytes)
        with os.fdopen(fd, 'wb') as f:
            f.write(encrypted)
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
    If MONEYPRINTER_CACHE_KEY is set and the file is encrypted, decrypts it.

    Args:
        path: The file path to read.
        default: Default value if file doesn't exist or is invalid.

    Returns:
        The parsed JSON dict.

    Raises:
        ValueError: If the file appears encrypted but no key is configured.
    """
    if default is None:
        default = {}
    try:
        with open(path, 'rb') as f:
            raw = f.read()
        decrypted = _decrypt_bytes(raw)
        parsed = json.loads(decrypted.decode("utf-8"))
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
