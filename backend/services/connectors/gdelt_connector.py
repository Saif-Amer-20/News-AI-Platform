from __future__ import annotations

from django.conf import settings

from services.integrations.gdelt_adapter import GDELTAdapter


class GDELTConnector:
    def __init__(self):
        self.adapter = GDELTAdapter(
            user_agent=getattr(settings, "HTTP_USER_AGENT", "NewsIntelBot/1.0"),
            timeout=30,
        )

    def fetch(self, source):
        return self.adapter.fetch(
            query=source.parser_config.get("query") or source.name,
            endpoint_url=source.fetch_url,
            max_records=int(source.parser_config.get("max_records", 10)),
            sort=source.parser_config.get("sort", "HybridRel"),
        )
