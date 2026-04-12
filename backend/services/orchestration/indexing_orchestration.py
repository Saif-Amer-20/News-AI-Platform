from __future__ import annotations

import logging

from .opensearch_service import OpenSearchService

logger = logging.getLogger(__name__)


class IndexingOrchestrationService:
    def __init__(self):
        self._search: OpenSearchService | None = None

    @property
    def search(self) -> OpenSearchService:
        """Lazy-init to avoid import-time connections."""
        if self._search is None:
            self._search = OpenSearchService()
        return self._search

    def index_article(self, article) -> None:
        """Index an article into OpenSearch.  Failures are logged, not raised."""
        try:
            self.search.index_article(article)
            logger.debug("Indexed article %s into OpenSearch", article.id)
        except Exception:
            logger.warning(
                "OpenSearch indexing failed for article %s — will retry on next sweep",
                article.id,
                exc_info=True,
            )

    def index_event(self, event) -> None:
        """Index an event into OpenSearch."""
        try:
            self.search.index_event(event)
            logger.debug("Indexed event %s into OpenSearch", event.id)
        except Exception:
            logger.warning(
                "OpenSearch indexing failed for event %s",
                event.id,
                exc_info=True,
            )

    def ensure_indices(self) -> None:
        """Bootstrap index mappings (safe to call repeatedly)."""
        try:
            self.search.ensure_indices()
        except Exception:
            logger.warning("OpenSearch index bootstrap failed", exc_info=True)
