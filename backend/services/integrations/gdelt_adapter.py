"""GDELT API integration adapter."""

from __future__ import annotations

import logging

import requests

from .common import BaseAdapter, IntegrationError, RawFetchResult, parse_datetime_value

logger = logging.getLogger(__name__)


class GDELTAdapter(BaseAdapter):
    service_name = "gdelt"
    default_endpoint = "https://api.gdeltproject.org/api/v2/doc/doc"

    def __init__(self, user_agent: str = "NewsIntelBot/1.0", timeout: int = 30):
        self._user_agent = user_agent
        self._timeout = timeout

    def fetch(self, query: str, *, endpoint_url: str | None = None, max_records: int = 10, sort: str = "HybridRel") -> list[RawFetchResult]:
        endpoint = endpoint_url or self.default_endpoint
        params = {
            "query": query,
            "mode": "ArtList",
            "format": "json",
            "sort": sort,
            "maxrecords": max_records,
        }
        try:
            response = requests.get(
                endpoint,
                params=params,
                timeout=self._timeout,
                headers={"User-Agent": self._user_agent},
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise IntegrationError(f"GDELT request failed for query '{query}': {exc}") from exc

        payload = response.json()
        articles = payload.get("articles", [])
        if not articles:
            raise IntegrationError(f"GDELT query '{query}' returned no articles.")

        results: list[RawFetchResult] = []
        for article in articles:
            results.append(
                RawFetchResult(
                    url=article.get("url", ""),
                    title_raw=article.get("title", ""),
                    content_raw=article.get("seendate", ""),
                    published_at=parse_datetime_value(article.get("seendate")),
                    image_url=article.get("socialimage", ""),
                    metadata={
                        "connector": "gdelt",
                        "domain": article.get("domain", ""),
                        "language": article.get("language", ""),
                        "source_country": article.get("sourcecountry", ""),
                        "social_image": article.get("socialimage", ""),
                        "tone": article.get("tone", ""),
                    },
                )
            )
        logger.info("Fetched %d items from GDELT for query '%s'", len(results), query)
        return results
