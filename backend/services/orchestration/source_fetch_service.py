"""Source fetch service — fetches raw items from a Source using the correct connector."""

from __future__ import annotations

import logging

from services.connectors.gdelt_connector import GDELTConnector
from services.connectors.gnews_connector import GNewsConnector
from services.connectors.html_connector import HTMLConnector
from services.connectors.newsapi_connector import NewsAPIConnector
from services.connectors.rss_connector import RSSConnector
from services.connectors.sitemap_connector import SitemapConnector
from services.integrations.common import IntegrationError, RawFetchResult
from sources.models import Source

logger = logging.getLogger(__name__)

_CONNECTOR_MAP = {
    "rss": RSSConnector,
    "sitemap": SitemapConnector,
    "html": HTMLConnector,
    "gdelt": GDELTConnector,
    "newsapi": NewsAPIConnector,
    "gnews": GNewsConnector,
}


class SourceFetchService:
    """Fetches raw items from a single Source via the connector strategy.

    Returns a list of RawFetchResult. Does NOT persist to DB — that is
    handled by RawItemService via IngestOrchestrationService.
    """

    def fetch_source(self, source: Source) -> list[RawFetchResult]:
        connector_cls = _CONNECTOR_MAP.get(source.parser_type)
        if connector_cls is None:
            raise IntegrationError(
                f"No connector for parser_type={source.parser_type!r} on source '{source.name}'"
            )
        connector = connector_cls()
        results = connector.fetch(source)
        logger.info(
            "SourceFetchService: fetched %d items for source %s (%s)",
            len(results), source.id, source.name,
        )
        return results
