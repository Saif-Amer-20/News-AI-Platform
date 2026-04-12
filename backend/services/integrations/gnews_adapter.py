"""GNews.io integration adapter."""

from __future__ import annotations

import logging

import requests
from django.conf import settings

from .common import BaseAdapter, IntegrationError, RawFetchResult, parse_datetime_value

logger = logging.getLogger(__name__)


class GNewsAdapter(BaseAdapter):
    service_name = "gnews"
    SEARCH_ENDPOINT = "https://gnews.io/api/v4/search"
    HEADLINES_ENDPOINT = "https://gnews.io/api/v4/top-headlines"

    def __init__(self, api_key: str = "", user_agent: str = "NewsIntelBot/1.0", timeout: int = 30):
        self._api_key = api_key or getattr(settings, "GNEWS_KEY", "")
        self._user_agent = user_agent
        self._timeout = timeout

    def fetch(
        self,
        *,
        endpoint_url: str | None = None,
        q: str = "",
        language: str = "",
        country: str = "",
        category: str = "",
        sort_by: str = "publishedAt",
        max_results: int = 10,
        page: int = 1,
        search_in: str = "",
    ) -> list[RawFetchResult]:
        if not self._api_key:
            raise IntegrationError("GNEWS_KEY is not configured.")

        # Decide endpoint: if explicit URL given use it, else headlines if no query
        if endpoint_url:
            endpoint = endpoint_url
        elif q:
            endpoint = self.SEARCH_ENDPOINT
        else:
            endpoint = self.HEADLINES_ENDPOINT

        is_search = "search" in endpoint

        params: dict = {
            "apikey": self._api_key,
            "max": min(max_results, 100),
            "page": page,
        }
        if q:
            params["q"] = q
        if language:
            params["lang"] = language
        if country:
            params["country"] = country
        if sort_by and is_search:
            params["sortby"] = sort_by
        if category and not is_search:
            params["category"] = category
        if search_in and is_search:
            params["in"] = search_in

        try:
            response = requests.get(
                endpoint,
                params=params,
                timeout=self._timeout,
                headers={"User-Agent": self._user_agent},
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise IntegrationError(f"GNews request failed: {exc}") from exc

        payload = response.json()
        if "errors" in payload:
            msg = ", ".join(payload["errors"])
            raise IntegrationError(f"GNews error: {msg}")

        articles = payload.get("articles", [])
        if not articles:
            logger.info("GNews returned 0 articles for endpoint=%s q=%s", endpoint, q)
            return []

        results: list[RawFetchResult] = []
        for article in articles:
            url = article.get("url", "")
            if not url:
                continue
            source_info = article.get("source") or {}
            results.append(
                RawFetchResult(
                    url=url,
                    title_raw=article.get("title") or "",
                    content_raw=article.get("description") or article.get("content") or "",
                    html_raw="",
                    published_at=parse_datetime_value(article.get("publishedAt")),
                    author="",
                    image_url=article.get("image") or "",
                    metadata={
                        "connector": "gnews",
                        "gnews_source_id": source_info.get("id", ""),
                        "gnews_source_name": source_info.get("name", ""),
                        "gnews_source_url": source_info.get("url", ""),
                    },
                )
            )

        logger.info("Fetched %d items from GNews (endpoint=%s, q=%s)", len(results), endpoint, q)
        return results
