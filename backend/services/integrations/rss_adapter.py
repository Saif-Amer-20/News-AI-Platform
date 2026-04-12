"""RSS feed integration adapter."""

from __future__ import annotations

import logging

import feedparser
import requests
from django.conf import settings

from .common import BaseAdapter, IntegrationError, RawFetchResult, clean_text, parse_datetime_value

logger = logging.getLogger(__name__)


class RSSAdapter(BaseAdapter):
    service_name = "rss"

    def __init__(self):
        self._user_agent = getattr(settings, "HTTP_USER_AGENT", "NewsIntelBot/1.0")
        self._timeout = 30

    def fetch(self, feed_url: str, timeout: int | None = None) -> list[RawFetchResult]:
        timeout = timeout or self._timeout
        try:
            resp = requests.get(
                feed_url,
                headers={"User-Agent": self._user_agent},
                timeout=timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise IntegrationError(f"RSS fetch failed for {feed_url}: {exc}") from exc

        feed = feedparser.parse(resp.content)
        items: list[RawFetchResult] = []
        for entry in feed.entries:
            content = ""
            if hasattr(entry, "content") and entry.content:
                content = entry.content[0].get("value", "")
            elif hasattr(entry, "summary"):
                content = entry.summary or ""

            items.append(
                RawFetchResult(
                    url=entry.get("link", ""),
                    title_raw=clean_text(entry.get("title", "")),
                    content_raw=content,
                    published_at=parse_datetime_value(entry.get("published") or entry.get("updated")),
                    author=clean_text(entry.get("author", "")),
                    metadata={
                        "feed_title": feed.feed.get("title", ""),
                        "tags": [t.get("term", "") for t in entry.get("tags", [])],
                    },
                )
            )
        logger.info("Fetched %d items from RSS feed %s", len(items), feed_url)
        return items
