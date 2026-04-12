from __future__ import annotations

import logging

from .neo4j_graph_service import Neo4jGraphService

logger = logging.getLogger(__name__)


class GraphWriteOrchestrationService:
    def __init__(self):
        self._graph: Neo4jGraphService | None = None

    @property
    def graph(self) -> Neo4jGraphService:
        if self._graph is None:
            self._graph = Neo4jGraphService()
        return self._graph

    def write_article_graph(self, article) -> None:
        """Write article and all relationships to Neo4j.  Failures are logged, not raised."""
        try:
            self.graph.write_article(article)
            logger.debug("Graph write completed for article %s", article.id)
        except Exception:
            logger.warning(
                "Neo4j graph write failed for article %s — will retry on next sweep",
                article.id,
                exc_info=True,
            )

    def ensure_schema(self) -> None:
        """Bootstrap Neo4j constraints and indexes (idempotent)."""
        try:
            self.graph.ensure_schema()
        except Exception:
            logger.warning("Neo4j schema bootstrap failed", exc_info=True)
