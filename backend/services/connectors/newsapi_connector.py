"""NewsAPI connector — bridges Source model config to the NewsAPI adapter."""

from __future__ import annotations

from django.conf import settings

from services.integrations.newsapi_adapter import NewsAPIAdapter


class NewsAPIConnector:
    def __init__(self):
        self.adapter = NewsAPIAdapter(
            user_agent=getattr(settings, "HTTP_USER_AGENT", "NewsIntelBot/1.0"),
            timeout=30,
        )

    def fetch(self, source):
        cfg = source.parser_config or {}
        endpoint = source.fetch_url or None

        return self.adapter.fetch(
            endpoint_url=endpoint,
            q=cfg.get("q", ""),
            sources=cfg.get("sources", ""),
            domains=cfg.get("domains", ""),
            language=cfg.get("language", "") or source.language or "",
            country=cfg.get("country", "") or source.country or "",
            category=cfg.get("category", ""),
            sort_by=cfg.get("sort_by", "publishedAt"),
            page_size=int(cfg.get("page_size", 20)),
            page=int(cfg.get("page", 1)),
        )
