from __future__ import annotations

from bs4 import BeautifulSoup

from services.integrations.common import RawFetchResult, clean_text
from services.integrations.rss_adapter import RSSAdapter

from .html_connector import HTMLConnector


class RSSConnector:
    def __init__(self):
        self.adapter = RSSAdapter()
        self.html_connector = HTMLConnector()

    def fetch(self, source) -> list[RawFetchResult]:
        results = self.adapter.fetch(source.fetch_url, timeout=source.request_timeout_seconds)
        fetch_full_article = source.parser_config.get("fetch_full_article", True)
        max_items = int(source.parser_config.get("max_items", 20))

        enriched_results: list[RawFetchResult] = []
        for result in results[:max_items]:
            if fetch_full_article and result.url:
                try:
                    full_article = self.html_connector.fetch_article(result.url, source)
                    enriched_results.append(
                        RawFetchResult(
                            url=result.url,
                            title_raw=full_article.title_raw or result.title_raw,
                            content_raw=full_article.content_raw or clean_text(BeautifulSoup(result.content_raw, "lxml").get_text(" ", strip=True)),
                            html_raw=full_article.html_raw or result.html_raw,
                            published_at=full_article.published_at or result.published_at,
                            author=full_article.author or result.author,
                            image_url=full_article.image_url or result.image_url,
                            metadata={**result.metadata, **full_article.metadata},
                        )
                    )
                    continue
                except Exception:
                    pass

            enriched_results.append(
                RawFetchResult(
                    url=result.url,
                    title_raw=result.title_raw,
                    content_raw=clean_text(BeautifulSoup(result.content_raw, "lxml").get_text(" ", strip=True)),
                    html_raw=result.html_raw,
                    published_at=result.published_at,
                    author=result.author,
                    image_url=result.image_url,
                    metadata=result.metadata,
                )
            )
        return enriched_results
