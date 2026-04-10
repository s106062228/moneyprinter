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

    def test_invalid_provider_raises(self):
        with pytest.raises(ValueError, match="Unsupported provider"):
            cache_module.get_provider_cache_path("instagram")


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
