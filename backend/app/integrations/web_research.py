"""Bounded, read-only public search and news adapters.

The adapters intentionally expose structured summaries only.  They do not accept a
caller supplied URL, send credentials, scrape result pages, or persist queries.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus, urlparse
from xml.etree import ElementTree

import httpx


MAX_QUERY_LENGTH = 200
MAX_RESULTS = 10
SEARCH_ENDPOINT = "https://api.duckduckgo.com/"
NEWS_ENDPOINT = "https://news.google.com/rss/search"


class WebResearchAdapter:
    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=10.0, follow_redirects=False)

    @staticmethod
    def _query(query: str) -> str:
        query = query.strip()
        if not 2 <= len(query) <= MAX_QUERY_LENGTH:
            raise ValueError(f"Query must be 2-{MAX_QUERY_LENGTH} characters")
        return query

    @staticmethod
    def _public_url(value: str) -> str | None:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            return None
        return value

    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        query = self._query(query)
        limit = max(1, min(int(limit), MAX_RESULTS))
        response = self.client.get(SEARCH_ENDPOINT, params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"})
        response.raise_for_status()
        payload = response.json()
        candidates = []
        if payload.get("AbstractText"):
            candidates.append({"title": payload.get("Heading") or query, "snippet": payload["AbstractText"], "url": payload.get("AbstractURL"), "source": payload.get("AbstractSource") or "DuckDuckGo"})
        for topic in payload.get("RelatedTopics", []):
            if isinstance(topic, dict) and "Topics" in topic:
                candidates.extend(topic["Topics"])
            else:
                candidates.append(topic)
        results = []
        for item in candidates:
            if not isinstance(item, dict) or not item.get("Text") and not item.get("snippet"):
                continue
            url = self._public_url(item.get("FirstURL") or item.get("url") or "")
            if not url:
                continue
            results.append({"title": item.get("Text", item.get("title", "Result")).split(" - ", 1)[0], "snippet": item.get("Text", item.get("snippet", "")), "url": url, "source": item.get("source", "DuckDuckGo")})
            if len(results) >= limit:
                break
        return {"query": query, "provider": "duckduckgo", "results": results, "retrieved_at": datetime.now(timezone.utc).isoformat()}

    def news(self, query: str, limit: int = 5) -> dict[str, Any]:
        query = self._query(query)
        limit = max(1, min(int(limit), MAX_RESULTS))
        response = self.client.get(NEWS_ENDPOINT, params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        results = []
        for item in root.findall("./channel/item"):
            url = self._public_url(item.findtext("link") or "")
            if not url:
                continue
            published = item.findtext("pubDate") or ""
            try:
                published = parsedate_to_datetime(published).astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError):
                pass
            source = item.find("source")
            results.append({"title": item.findtext("title") or "Untitled", "summary": item.findtext("description") or "", "url": url, "source": source.text if source is not None else "Google News", "published_at": published})
            if len(results) >= limit:
                break
        return {"query": query, "provider": "google_news_rss", "results": results, "retrieved_at": datetime.now(timezone.utc).isoformat()}


web_research_adapter = WebResearchAdapter()


def structured_web_search(query: str, limit: int = 5) -> dict[str, Any]:
    return web_research_adapter.search(query, limit)


def structured_news_search(query: str, limit: int = 5) -> dict[str, Any]:
    return web_research_adapter.news(query, limit)
