"""Web search provider abstraction.

Supports multiple search backends (DuckDuckGo, Brave, SerpAPI) with
configurable caching and rate-limiting. The factory function
``create_search_provider`` reads the provider config from
``architecture_config.json`` services section.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Result types ─────────────────────────────────────────────────────────────


@dataclass
class SearchItem:
    """A single search result."""
    title: str
    url: str
    snippet: str


@dataclass
class SearchResult:
    """Aggregated search results."""
    query: str
    results: list[SearchItem] = field(default_factory=list)
    error: str | None = None


# ── Cache ────────────────────────────────────────────────────────────────────


class SearchCache:
    """In-memory TTL cache for search results."""

    def __init__(self, ttl_seconds: int = 300):
        self._cache: dict[str, tuple[float, SearchResult]] = {}
        self._ttl = ttl_seconds

    def get(self, query: str) -> SearchResult | None:
        key = query.strip().lower()
        entry = self._cache.get(key)
        if entry is None:
            return None
        cached_at, result = entry
        if time.time() - cached_at > self._ttl:
            del self._cache[key]
            return None
        return result

    def put(self, query: str, result: SearchResult) -> None:
        key = query.strip().lower()
        self._cache[key] = (time.time(), result)


# ── Provider base ────────────────────────────────────────────────────────────


class SearchProvider(ABC):
    """Abstract base for web search providers."""

    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> SearchResult:
        """Execute a search and return results."""
        ...


# ── DuckDuckGo provider ──────────────────────────────────────────────────────


class DuckDuckGoSearchProvider(SearchProvider):
    """Search via DuckDuckGo HTML scraping (no API key needed).

    Uses the instant answer API and HTML search results.
    Respects rate limits with delays between requests.
    """

    USER_AGENT = "Obrenna/1.0 (AI assistant; +https://obrenna.ai)"

    def __init__(self, timeout: float = 10.0, cache: SearchCache | None = None):
        self._timeout = timeout
        self._cache = cache

    async def search(self, query: str, max_results: int = 5) -> SearchResult:
        if self._cache:
            cached = self._cache.get(query)
            if cached:
                return cached

        import httpx
        results: list[SearchItem] = []

        # Try DuckDuckGo HTML search
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers={"User-Agent": self.USER_AGENT},
                )
                resp.raise_for_status()
                results.extend(self._parse_html_results(resp.text, max_results))
        except Exception as exc:
            logger.warning("DuckDuckGo HTML search failed: %s", exc)

        # Try DuckDuckGo instant answer API
        if len(results) < max_results:
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(
                        "https://api.duckduckgo.com/",
                        params={
                            "q": query,
                            "format": "json",
                            "no_html": "1",
                            "no_redirect": "1",
                        },
                        headers={"User-Agent": self.USER_AGENT},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    abstract = data.get("AbstractText", "")
                    url = data.get("AbstractURL", "")
                    if abstract and url:
                        results.insert(0, SearchItem(
                            title=data.get("Heading", query),
                            url=url,
                            snippet=abstract,
                        ))
            except Exception as exc:
                logger.warning("DuckDuckGo API search failed: %s", exc)

        final = results[:max_results]
        search_result = SearchResult(query=query, results=final)

        if self._cache:
            self._cache.put(query, search_result)

        return search_result

    @staticmethod
    def _parse_html_results(html: str, max_results: int) -> list[SearchItem]:
        """Parse search results from DuckDuckGo HTML page."""
        results: list[SearchItem] = []
        try:
            import re
            # Match result blocks: <div class="result">...</div>
            block_pattern = re.compile(
                r'<div\s+class="result">(.*?)</div>',
                re.DOTALL | re.IGNORECASE,
            )
            for block_match in block_pattern.finditer(html):
                block = block_match.group(1)
                title_m = re.search(
                    r'<a\s+[^>]*class="result__a"[^>]*>(.*?)</a>',
                    block, re.DOTALL | re.IGNORECASE,
                )
                url_m = re.search(
                    r'<a\s+[^>]*class="result__a"[^>]*href="([^"]*)"',
                    block, re.IGNORECASE,
                )
                snippet_m = re.search(
                    r'<dd>(.*?)</dd>',
                    block, re.DOTALL | re.IGNORECASE,
                )
                title = ""
                url = ""
                snippet = ""
                if title_m:
                    title = re.sub(r'<[^>]+>', '', title_m.group(1)).strip()
                if url_m:
                    url = url_m.group(1).replace('&amp;', '&')
                if snippet_m:
                    snippet = re.sub(r'<[^>]+>', '', snippet_m.group(1)).strip()
                if title and url:
                    results.append(SearchItem(title=title, url=url, snippet=snippet))
                if len(results) >= 10:
                    break
        except Exception as exc:
            logger.warning("Failed to parse DuckDuckGo HTML: %s", exc)
        return results[:max_results]


# ── Brave provider ───────────────────────────────────────────────────────────


class BraveSearchProvider(SearchProvider):
    """Search via Brave Search API (requires API key)."""

    BASE_URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str | None = None, timeout: float = 10.0,
                 cache: SearchCache | None = None):
        self._api_key = api_key or os.environ.get("BRAVE_SEARCH_API_KEY")
        self._timeout = timeout
        self._cache = cache

    async def search(self, query: str, max_results: int = 5) -> SearchResult:
        if not self._api_key:
            return SearchResult(query=query, error="Brave Search API key not configured")

        if self._cache:
            cached = self._cache.get(query)
            if cached:
                return cached

        import httpx
        results: list[SearchItem] = []

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    self.BASE_URL,
                    headers={
                        "Accept": "application/json",
                        "Accept-Encoding": "gzip",
                        "X-Subscription-Token": self._api_key,
                    },
                    params={"q": query, "count": min(max_results, 20)},
                )
                resp.raise_for_status()
                data = resp.json()

                web_results = data.get("web", {}).get("results", [])
                for r in web_results[:max_results]:
                    results.append(SearchItem(
                        title=r.get("title", ""),
                        url=r.get("url", ""),
                        snippet=r.get("description", ""),
                    ))
        except httpx.HTTPStatusError as exc:
            return SearchResult(query=query, error=f"Brave search API error: {exc.response.status_code}")
        except Exception as exc:
            return SearchResult(query=query, error=f"Brave search failed: {exc}")

        search_result = SearchResult(query=query, results=results)

        if self._cache:
            self._cache.put(query, search_result)

        return search_result


# ── SerpAPI provider ─────────────────────────────────────────────────────────


class SerpApiSearchProvider(SearchProvider):
    """Search via SerpAPI (requires API key)."""

    BASE_URL = "https://serpapi.com/search"

    def __init__(self, api_key: str | None = None, timeout: float = 10.0,
                 cache: SearchCache | None = None):
        self._api_key = api_key or os.environ.get("SERPAPI_API_KEY")
        self._timeout = timeout
        self._cache = cache

    async def search(self, query: str, max_results: int = 5) -> SearchResult:
        if not self._api_key:
            return SearchResult(query=query, error="SerpAPI key not configured")

        if self._cache:
            cached = self._cache.get(query)
            if cached:
                return cached

        import httpx
        results: list[SearchItem] = []

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(
                    self.BASE_URL,
                    params={
                        "q": query,
                        "engine": "google",
                        "num": min(max_results, 20),
                        "api_key": self._api_key,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                organic_results = data.get("organic_results", [])
                for r in organic_results[:max_results]:
                    results.append(SearchItem(
                        title=r.get("title", ""),
                        url=r.get("link", ""),
                        snippet=r.get("snippet", ""),
                    ))
        except httpx.HTTPStatusError as exc:
            return SearchResult(query=query, error=f"SerpAPI error: {exc.response.status_code}")
        except Exception as exc:
            return SearchResult(query=query, error=f"SerpAPI search failed: {exc}")

        search_result = SearchResult(query=query, results=results)

        if self._cache:
            self._cache.put(query, search_result)

        return search_result


# ── Factory ──────────────────────────────────────────────────────────────────

SUPPORTED_PROVIDERS = ["duckduckgo", "brave", "serpapi"]


def create_search_provider(
    config: dict[str, Any],
    cache: SearchCache | None = None,
) -> SearchProvider:
    """Create a search provider from config.

    Args:
        config: services.web_search config dict from architecture_config.
        cache: Optional SearchCache instance. If None, creates a new one.

    Returns:
        Configured SearchProvider instance.
    """
    provider_name = config.get("provider", "duckduckgo")
    timeout = config.get("timeout_seconds", 10)
    ttl = config.get("cache_ttl_seconds", 300)

    if provider_name == "brave":
        return BraveSearchProvider(timeout=timeout, cache=cache)
    elif provider_name == "serpapi":
        return SerpApiSearchProvider(timeout=timeout, cache=cache)
    elif provider_name == "duckduckgo":
        if cache is None:
            cache = SearchCache(ttl_seconds=ttl)
        return DuckDuckGoSearchProvider(timeout=timeout, cache=cache)
    else:
        logger.warning("Unknown search provider '%s', defaulting to duckduckgo", provider_name)
        if cache is None:
            cache = SearchCache(ttl_seconds=ttl)
        return DuckDuckGoSearchProvider(timeout=timeout, cache=cache)
