"""Tests for search provider abstraction."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.search import (
    DuckDuckGoSearchProvider,
    BraveSearchProvider,
    SerpApiSearchProvider,
    SearchCache,
    SearchItem,
    SearchProvider,
    SearchResult,
    create_search_provider,
)


class TestSearchCache:
    """Test search result caching."""

    def test_cache_miss(self):
        cache = SearchCache(ttl_seconds=300)
        result = cache.get("test query")
        assert result is None

    def test_cache_put_and_get(self):
        cache = SearchCache(ttl_seconds=300)
        result = SearchResult(query="test", results=[SearchItem(title="T", url="http://t.com", snippet="S")])
        cache.put("test query", result)
        retrieved = cache.get("test query")
        assert retrieved is not None
        assert retrieved.query == "test"
        assert len(retrieved.results) == 1

    def test_cache_case_insensitive(self):
        cache = SearchCache(ttl_seconds=300)
        result = SearchResult(query="test")
        cache.put("TEST QUERY", result)
        assert cache.get("test query") is not None

    def test_cache_ttl_expiry(self):
        cache = SearchCache(ttl_seconds=0)  # 0 TTL = immediate expiry
        result = SearchResult(query="test")
        cache.put("test query", result)
        import time
        time.sleep(0.01)  # Small delay to exceed 0 TTL
        assert cache.get("test query") is None

    def test_cache_ttl_hit_within_ttl(self):
        cache = SearchCache(ttl_seconds=10)
        result = SearchResult(query="test")
        cache.put("test query", result)
        assert cache.get("test query") is not None


class TestDuckDuckGoProvider:
    """Test DuckDuckGo search provider."""

    def test_parse_html_results(self):
        html = '''
        <div class="result">
          <a class="result__a" href="http://example.com/1">Example Title 1</a>
          <dd>This is a test snippet for the first result.</dd>
        </div>
        <div class="result">
          <a class="result__a" href="http://example.com/2">Example Title 2</a>
          <dd>This is a test snippet for the second result.</dd>
        </div>
        '''
        results = DuckDuckGoSearchProvider._parse_html_results(html, 10)
        assert len(results) == 2
        assert results[0].title == "Example Title 1"
        assert "example.com/1" in results[0].url
        assert "test snippet" in results[0].snippet

    def test_parse_html_results_limited(self):
        html = '''
        <div class="result">
          <a class="result__a" href="http://example.com/1">Title 1</a>
          <dd>Snippet 1</dd>
        </div>
        <div class="result">
          <a class="result__a" href="http://example.com/2">Title 2</a>
          <dd>Snippet 2</dd>
        </div>
        '''
        results = DuckDuckGoSearchProvider._parse_html_results(html, 1)
        assert len(results) == 1

    def test_parse_html_results_empty(self):
        results = DuckDuckGoSearchProvider._parse_html_results("<p>No results</p>", 10)
        assert len(results) == 0


class TestBraveProvider:
    """Test Brave Search provider."""

    @pytest.mark.asyncio
    async def test_no_api_key(self):
        provider = BraveSearchProvider(api_key=None)
        result = await provider.search("test query")
        assert result.error is not None
        assert "API key not configured" in result.error

    @pytest.mark.asyncio
    async def test_search_with_mock(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "web": {
                "results": [
                    {
                        "title": "Brave Result 1",
                        "url": "https://example.com/1",
                        "description": "Brave search description 1",
                    }
                ]
            }
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch('httpx.AsyncClient', return_value=mock_client):
            provider = BraveSearchProvider(api_key="fake_key")
            result = await provider.search("test query")
            assert result.error is None
            assert len(result.results) == 1
            assert result.results[0].title == "Brave Result 1"


class TestSerpApiProvider:
    """Test SerpAPI search provider."""

    @pytest.mark.asyncio
    async def test_no_api_key(self):
        provider = SerpApiSearchProvider(api_key=None)
        result = await provider.search("test query")
        assert result.error is not None
        assert "SerpAPI key not configured" in result.error


class TestFactory:
    """Test search provider factory."""

    def test_duckduckgo_default(self):
        config = {"provider": "duckduckgo", "timeout_seconds": 10}
        provider = create_search_provider(config)
        assert isinstance(provider, DuckDuckGoSearchProvider)

    def test_brave(self):
        config = {"provider": "brave", "timeout_seconds": 5}
        provider = create_search_provider(config)
        assert isinstance(provider, BraveSearchProvider)

    def test_serpapi(self):
        config = {"provider": "serpapi", "timeout_seconds": 15}
        provider = create_search_provider(config)
        assert isinstance(provider, SerpApiSearchProvider)

    def test_unknown_defaults_to_duckduckgo(self):
        config = {"provider": "unknown_provider"}
        provider = create_search_provider(config)
        assert isinstance(provider, DuckDuckGoSearchProvider)


class TestSearchProviderABC:
    """Test that SearchProvider is abstract."""

    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            SearchProvider()
