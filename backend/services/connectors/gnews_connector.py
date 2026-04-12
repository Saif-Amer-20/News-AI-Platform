"""GNews connector — bridges Source model config to the GNews adapter."""

from __future__ import annotations

from django.conf import settings

from services.integrations.gnews_adapter import GNewsAdapter


class GNewsConnector:
    def __init__(self):
        self.adapter = GNewsAdapter(
            user_agent=getattr(settings, "HTTP_USER_AGENT", "NewsIntelBot/1.0"),
            timeout=30,
        )

    def fetch(self, source):
        cfg = source.parser_config or {}
        endpoint = source.fetch_url or None

        return self.adapter.fetch(
            endpoint_url=endpoint,
            q=cfg.get("q", ""),
            language=cfg.get("language", "") or source.language or "",
            country=cfg.get("country", "") or source.country or "",
            category=cfg.get("category", ""),
            sort_by=cfg.get("sort_by", "publishedAt"),
            max_results=int(cfg.get("max_results", 10)),
            page=int(cfg.get("page", 1)),
            search_in=cfg.get("search_in", ""),
        )
