"""NewsAPI.org integration adapter."""

from __future__ import annotations

import logging

import requests
from django.conf import settings

from .common import BaseAdapter, IntegrationError, RawFetchResult, parse_datetime_value

logger = logging.getLogger(__name__)


class NewsAPIAdapter(BaseAdapter):
    service_name = "newsapi"
    default_endpoint = "https://newsapi.org/v2/everything"

    def __init__(self, api_key: str = "", user_agent: str = "NewsIntelBot/1.0", timeout: int = 30):
        self._api_key = api_key or getattr(settings, "NEWSAPI_KEY", "")
        self._user_agent = user_agent
        self._timeout = timeout

    def fetch(
        self,
        *,
        endpoint_url: str | None = None,
        q: str = "",
        sources: str = "",
        domains: str = "",
        language: str = "",
        country: str = "",
        category: str = "",
        sort_by: str = "publishedAt",
        page_size: int = 20,
        page: int = 1,
    ) -> list[RawFetchResult]:
        if not self._api_key:
            raise IntegrationError("NEWSAPI_KEY is not configured.")

        endpoint = endpoint_url or self.default_endpoint
        is_top_headlines = "top-headlines" in endpoint

        params: dict = {"apiKey": self._api_key, "pageSize": page_size, "page": page}
        if q:
            params["q"] = q
        if sources:
            params["sources"] = sources
        if language:
            params["language"] = language
        if sort_by and not is_top_headlines:
            params["sortBy"] = sort_by
        if domains and not is_top_headlines:
            params["domains"] = domains
        if country and is_top_headlines:
            params["country"] = country
        if category and is_top_headlines:
            params["category"] = category

        try:
            response = requests.get(
                endpoint,
                params=params,
                timeout=self._timeout,
                headers={"User-Agent": self._user_agent},
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise IntegrationError(f"NewsAPI request failed: {exc}") from exc

        payload = response.json()
        if payload.get("status") != "ok":
            msg = payload.get("message", "Unknown NewsAPI error")
            raise IntegrationError(f"NewsAPI error: {msg}")

        articles = payload.get("articles", [])
        if not articles:
            logger.info("NewsAPI returned 0 articles for endpoint=%s q=%s", endpoint, q)
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
                    content_raw=article.get("description") or "",
                    html_raw="",
                    published_at=parse_datetime_value(article.get("publishedAt")),
                    author=article.get("author") or "",
                    image_url=article.get("urlToImage") or "",
                    metadata={
                        "connector": "newsapi",
                        "newsapi_source_id": source_info.get("id", ""),
                        "newsapi_source_name": source_info.get("name", ""),
                    },
                )
            )

        logger.info("Fetched %d items from NewsAPI (endpoint=%s, q=%s)", len(results), endpoint, q)
        return results
