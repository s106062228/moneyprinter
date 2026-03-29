"""
Tests for src/cache.py — JSON-based data persistence.
"""

import os
import json
import pytest
from unittest.mock import patch

import cache as cache_module
from config import ROOT_DIR


@pytest.fixture(autouse=True)
def isolate_cache(tmp_path):
    """Redirect cache to use temp directory."""
    mp_dir = str(tmp_path / ".mp")
    os.makedirs(mp_dir, exist_ok=True)
    with patch.object(cache_module, "ROOT_DIR", str(tmp_path)):
        yield tmp_path


class TestCachePaths:
    """Tests for cache path helpers."""

    def test_get_cache_path(self, isolate_cache):
        assert cache_module.get_cache_path() == str(isolate_cache / ".mp")

    def test_get_twitter_cache_path(self, isolate_cache):
        result = cache_module.get_twitter_cache_path()
        assert result.endswith("twitter.json")

    def test_get_youtube_cache_path(self, isolate_cache):
        result = cache_module.get_youtube_cache_path()
        assert result.endswith("youtube.json")

    def test_get_afm_cache_path(self, isolate_cache):
        result = cache_module.get_afm_cache_path()
        assert result.endswith("afm.json")

    def test_get_results_cache_path(self, isolate_cache):
        result = cache_module.get_results_cache_path()
        assert result.endswith("scraper_results.csv")


class TestProviderCachePath:
    """Tests for get_provider_cache_path()."""

    def test_twitter_provider(self, isolate_cache):
        result = cache_module.get_provider_cache_path("twitter")
        assert "twitter.json" in result

    def test_youtube_provider(self, isolate_cache):
        result = cache_module.get_provider_cache_path("youtube")
        assert "youtube.json" in result

    def test_instagram_provider(self, isolate_cache):
        result = cache_module.get_provider_cache_path("instagram")
        assert "instagram.json" in result

    def test_invalid_provider_raises(self):
        with pytest.raises(ValueError, match="Unsupported provider"):
            cache_module.get_provider_cache_path("snapchat")


class TestAccounts:
    """Tests for account CRUD operations."""

    def test_get_accounts_empty(self, isolate_cache):
        """Returns empty list when no accounts exist."""
        accounts = cache_module.get_accounts("twitter")
        assert accounts == []

    def test_add_and_get_account(self, isolate_cache):
        """Adds an account and retrieves it."""
        account = {"id": "abc-123", "nickname": "test", "firefox_profile": "/tmp/profile", "topic": "tech"}
        cache_module.add_account("twitter", account)

        accounts = cache_module.get_accounts("twitter")
        assert len(accounts) == 1
        assert accounts[0]["id"] == "abc-123"
        assert accounts[0]["nickname"] == "test"

    def test_add_multiple_accounts(self, isolate_cache):
        """Adds multiple accounts."""
        cache_module.add_account("youtube", {"id": "1", "nickname": "a", "firefox_profile": "/p", "niche": "x", "language": "en"})
        cache_module.add_account("youtube", {"id": "2", "nickname": "b", "firefox_profile": "/q", "niche": "y", "language": "en"})

        accounts = cache_module.get_accounts("youtube")
        assert len(accounts) == 2

    def test_remove_account(self, isolate_cache):
        """Removes an account by ID."""
        cache_module.add_account("twitter", {"id": "to-remove", "nickname": "rm"})
        cache_module.add_account("twitter", {"id": "to-keep", "nickname": "keep"})

        cache_module.remove_account("twitter", "to-remove")
        accounts = cache_module.get_accounts("twitter")
        assert len(accounts) == 1
        assert accounts[0]["id"] == "to-keep"

    def test_remove_nonexistent_account(self, isolate_cache):
        """Removing a non-existent account doesn't error."""
        cache_module.add_account("twitter", {"id": "exists", "nickname": "e"})
        cache_module.remove_account("twitter", "does-not-exist")
        accounts = cache_module.get_accounts("twitter")
        assert len(accounts) == 1


class TestProducts:
    """Tests for product CRUD operations."""

    def test_get_products_empty(self, isolate_cache):
        """Returns empty list when no products exist."""
        products = cache_module.get_products()
        assert products == []

    def test_add_and_get_product(self, isolate_cache):
        """Adds a product and retrieves it."""
        product = {"name": "Widget", "url": "https://amazon.com/widget", "price": "$19.99"}
        cache_module.add_product(product)

        products = cache_module.get_products()
        assert len(products) == 1
        assert products[0]["name"] == "Widget"

    def test_add_multiple_products(self, isolate_cache):
        """Adds multiple products."""
        cache_module.add_product({"name": "A"})
        cache_module.add_product({"name": "B"})
        cache_module.add_product({"name": "C"})

        products = cache_module.get_products()
        assert len(products) == 3


# ---------------------------------------------------------------------------
# Encryption tests
# ---------------------------------------------------------------------------

@pytest.fixture
def encrypted_cache(tmp_path, monkeypatch):
    """Set up an encrypted cache environment."""
    from cryptography.fernet import Fernet as _Fernet
    key = _Fernet.generate_key()
    monkeypatch.setenv("MONEYPRINTER_CACHE_KEY", key.decode())
    # Reset fernet cache so it picks up the new key
    from cache import _reset_fernet
    _reset_fernet()
    # Redirect ROOT_DIR to tmp_path
    monkeypatch.setattr("cache.ROOT_DIR", str(tmp_path))
    yield key
    _reset_fernet()


class TestGetFernet:
    """Tests for _get_fernet() helper."""

    def test_returns_none_when_no_env_var(self):
        """Returns None when MONEYPRINTER_CACHE_KEY is not set."""
        cache_module._reset_fernet()
        assert "MONEYPRINTER_CACHE_KEY" not in os.environ
        result = cache_module._get_fernet()
        assert result is None
        cache_module._reset_fernet()

    def test_returns_fernet_instance_when_env_var_set(self, monkeypatch):
        """Returns a Fernet instance when env var is set."""
        from cryptography.fernet import Fernet, Fernet as _Fernet
        key = _Fernet.generate_key()
        monkeypatch.setenv("MONEYPRINTER_CACHE_KEY", key.decode())
        cache_module._reset_fernet()
        result = cache_module._get_fernet()
        assert result is not None
        assert isinstance(result, Fernet)
        cache_module._reset_fernet()

    def test_caches_instance_on_second_call(self, monkeypatch):
        """Second call returns the same Fernet object (module-level cache)."""
        from cryptography.fernet import Fernet as _Fernet
        key = _Fernet.generate_key()
        monkeypatch.setenv("MONEYPRINTER_CACHE_KEY", key.decode())
        cache_module._reset_fernet()
        first = cache_module._get_fernet()
        second = cache_module._get_fernet()
        assert first is second
        cache_module._reset_fernet()

    def test_returns_none_when_cryptography_not_installed(self, monkeypatch):
        """Returns None gracefully when cryptography package is missing."""
        from cryptography.fernet import Fernet as _Fernet
        key = _Fernet.generate_key()
        monkeypatch.setenv("MONEYPRINTER_CACHE_KEY", key.decode())
        cache_module._reset_fernet()

        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "cryptography.fernet":
                raise ImportError("cryptography not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        result = cache_module._get_fernet()
        assert result is None
        cache_module._reset_fernet()

    def test_reset_fernet_clears_cache(self, monkeypatch):
        """_reset_fernet() clears both module-level globals."""
        from cryptography.fernet import Fernet as _Fernet
        key = _Fernet.generate_key()
        monkeypatch.setenv("MONEYPRINTER_CACHE_KEY", key.decode())
        cache_module._reset_fernet()
        cache_module._get_fernet()  # populate cache
        assert cache_module._fernet_checked is True
        cache_module._reset_fernet()
        assert cache_module._fernet_checked is False
        assert cache_module._fernet_instance is None


class TestEncryptDecryptBytes:
    """Tests for _encrypt_bytes and _decrypt_bytes."""

    def test_round_trip_with_key(self, encrypted_cache):
        """Encrypt then decrypt returns the original bytes."""
        original = b'{"hello": "world"}'
        encrypted = cache_module._encrypt_bytes(original)
        result = cache_module._decrypt_bytes(encrypted)
        assert result == original

    def test_no_op_when_no_key(self):
        """Without a key, _encrypt_bytes returns data unchanged."""
        cache_module._reset_fernet()
        data = b'{"key": "value"}'
        result = cache_module._encrypt_bytes(data)
        assert result == data
        cache_module._reset_fernet()

    def test_encrypted_data_starts_with_gaaaaa(self, encrypted_cache):
        """Fernet tokens always start with 'gAAAAA'."""
        data = b'{"test": true}'
        encrypted = cache_module._encrypt_bytes(data)
        assert encrypted.startswith(b"gAAAAA")

    def test_decrypt_plaintext_when_key_is_set(self, encrypted_cache):
        """Decrypting plaintext (no gAAAAA prefix) returns data as-is."""
        plaintext = b'{"accounts": []}'
        result = cache_module._decrypt_bytes(plaintext)
        assert result == plaintext

    def test_decrypt_with_wrong_key_raises(self, monkeypatch):
        """Decrypting data encrypted with a different key raises InvalidToken."""
        from cryptography.fernet import Fernet as _Fernet, InvalidToken

        key_a = _Fernet.generate_key()
        key_b = _Fernet.generate_key()

        # Encrypt with key_a
        monkeypatch.setenv("MONEYPRINTER_CACHE_KEY", key_a.decode())
        cache_module._reset_fernet()
        encrypted = cache_module._encrypt_bytes(b'{"data": "secret"}')

        # Try to decrypt with key_b
        monkeypatch.setenv("MONEYPRINTER_CACHE_KEY", key_b.decode())
        cache_module._reset_fernet()
        with pytest.raises(InvalidToken):
            cache_module._decrypt_bytes(encrypted)
        cache_module._reset_fernet()

    def test_decrypt_encrypted_without_key_raises_valueerror(self, monkeypatch):
        """Decrypting an encrypted file without a key raises ValueError."""
        from cryptography.fernet import Fernet as _Fernet

        key = _Fernet.generate_key()
        monkeypatch.setenv("MONEYPRINTER_CACHE_KEY", key.decode())
        cache_module._reset_fernet()
        encrypted = cache_module._encrypt_bytes(b'{"secret": "data"}')

        # Remove the key and reset
        monkeypatch.delenv("MONEYPRINTER_CACHE_KEY")
        cache_module._reset_fernet()

        with pytest.raises(ValueError, match="MONEYPRINTER_CACHE_KEY"):
            cache_module._decrypt_bytes(encrypted)
        cache_module._reset_fernet()


class TestEncryptedCacheOperations:
    """Tests for cache CRUD operations with encryption enabled."""

    def test_safe_write_read_round_trip(self, encrypted_cache, tmp_path):
        """_safe_write_json then _safe_read_json returns original data."""
        path = str(tmp_path / ".mp" / "test.json")
        data = {"accounts": [{"id": "1", "nickname": "enc_user"}]}
        cache_module._safe_write_json(path, data)
        result = cache_module._safe_read_json(path)
        assert result == data

    def test_add_and_get_account_encrypted(self, encrypted_cache):
        """add_account and get_accounts work correctly with encryption."""
        account = {"id": "enc-abc", "nickname": "encrypted_user"}
        cache_module.add_account("twitter", account)
        accounts = cache_module.get_accounts("twitter")
        assert len(accounts) == 1
        assert accounts[0]["id"] == "enc-abc"
        assert accounts[0]["nickname"] == "encrypted_user"

    def test_add_and_get_product_encrypted(self, encrypted_cache):
        """add_product and get_products work correctly with encryption."""
        product = {"name": "SecureWidget", "price": "$9.99"}
        cache_module.add_product(product)
        products = cache_module.get_products()
        assert len(products) == 1
        assert products[0]["name"] == "SecureWidget"

    def test_remove_account_encrypted(self, encrypted_cache):
        """remove_account works correctly with encryption."""
        cache_module.add_account("youtube", {"id": "keep-me", "nickname": "keeper"})
        cache_module.add_account("youtube", {"id": "remove-me", "nickname": "gone"})
        cache_module.remove_account("youtube", "remove-me")
        accounts = cache_module.get_accounts("youtube")
        assert len(accounts) == 1
        assert accounts[0]["id"] == "keep-me"

    def test_file_on_disk_is_not_readable_json(self, encrypted_cache, tmp_path):
        """Encrypted file on disk cannot be parsed as plain JSON."""
        cache_module.add_account("twitter", {"id": "secret", "nickname": "hidden"})
        cache_path = str(tmp_path / ".mp" / "twitter.json")
        with open(cache_path, 'rb') as f:
            raw = f.read()
        # Should start with Fernet token prefix, not '{'
        assert raw.startswith(b"gAAAAA")
        with pytest.raises(Exception):
            json.loads(raw.decode("utf-8", errors="replace"))

    def test_large_data_round_trip(self, encrypted_cache, tmp_path):
        """Large datasets survive an encrypted write/read cycle."""
        path = str(tmp_path / ".mp" / "large.json")
        large_data = {
            "products": [
                {"id": str(i), "name": f"Product {i}", "desc": "x" * 500}
                for i in range(100)
            ]
        }
        cache_module._safe_write_json(path, large_data)
        result = cache_module._safe_read_json(path)
        assert len(result["products"]) == 100
        assert result["products"][42]["name"] == "Product 42"


class TestCacheBackwardCompatibility:
    """Tests for backward compatibility with plaintext caches."""

    def test_plaintext_write_and_read_without_key(self, tmp_path, monkeypatch):
        """Without a key, data is written and read as plain JSON (unchanged behavior)."""
        cache_module._reset_fernet()
        monkeypatch.setattr("cache.ROOT_DIR", str(tmp_path))
        path = str(tmp_path / ".mp" / "plain.json")
        data = {"accounts": [{"id": "plain-1"}]}
        cache_module._safe_write_json(path, data)
        # Raw file should be readable JSON
        with open(path, 'rb') as f:
            raw = f.read()
        parsed = json.loads(raw.decode("utf-8"))
        assert parsed == data
        # And _safe_read_json also returns it correctly
        result = cache_module._safe_read_json(path)
        assert result == data
        cache_module._reset_fernet()

    def test_plaintext_file_readable_after_key_set(self, tmp_path, monkeypatch):
        """A plaintext file written without a key is still readable after a key is set."""
        # Write without a key
        cache_module._reset_fernet()
        monkeypatch.setattr("cache.ROOT_DIR", str(tmp_path))
        path = str(tmp_path / ".mp" / "compat.json")
        data = {"accounts": [{"id": "old-plain"}]}
        cache_module._safe_write_json(path, data)

        # Now set a key and try to read the plaintext file
        from cryptography.fernet import Fernet as _Fernet
        key = _Fernet.generate_key()
        monkeypatch.setenv("MONEYPRINTER_CACHE_KEY", key.decode())
        cache_module._reset_fernet()

        result = cache_module._safe_read_json(path)
        assert result == data
        cache_module._reset_fernet()

    def test_encrypted_file_unreadable_without_key(self, tmp_path, monkeypatch):
        """An encrypted file raises ValueError when read without a key."""
        from cryptography.fernet import Fernet as _Fernet
        key = _Fernet.generate_key()
        monkeypatch.setenv("MONEYPRINTER_CACHE_KEY", key.decode())
        cache_module._reset_fernet()
        monkeypatch.setattr("cache.ROOT_DIR", str(tmp_path))

        path = str(tmp_path / ".mp" / "encrypted.json")
        cache_module._safe_write_json(path, {"secret": "value"})

        # Remove key and reset
        monkeypatch.delenv("MONEYPRINTER_CACHE_KEY")
        cache_module._reset_fernet()

        with pytest.raises(ValueError, match="MONEYPRINTER_CACHE_KEY"):
            cache_module._safe_read_json(path)
        cache_module._reset_fernet()

    def test_multiple_accounts_plaintext_consistency(self, tmp_path, monkeypatch):
        """Multiple add/get cycles work the same in plaintext mode."""
        cache_module._reset_fernet()
        monkeypatch.setattr("cache.ROOT_DIR", str(tmp_path))
        for i in range(5):
            cache_module.add_account("instagram", {"id": f"user-{i}", "nickname": f"n{i}"})
        accounts = cache_module.get_accounts("instagram")
        assert len(accounts) == 5
        assert accounts[3]["id"] == "user-3"
        cache_module._reset_fernet()
