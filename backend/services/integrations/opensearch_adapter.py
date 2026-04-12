"""OpenSearch integration adapter."""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from opensearchpy import OpenSearch, RequestsHttpConnection

from .common import BaseAdapter, IntegrationError

logger = logging.getLogger(__name__)


class OpenSearchAdapter(BaseAdapter):
    service_name = "opensearch"

    def __init__(self):
        url = getattr(settings, "OPENSEARCH_URL", "http://opensearch:9200")
        self._client = OpenSearch(
            hosts=[url],
            connection_class=RequestsHttpConnection,
            use_ssl=url.startswith("https"),
            verify_certs=False,
            timeout=30,
        )

    # ── Index management ──────────────────────────────────────────────

    def ensure_index(self, index_name: str, body: dict | None = None) -> bool:
        try:
            if not self._client.indices.exists(index=index_name):
                self._client.indices.create(index=index_name, body=body or {})
                logger.info("Created index %s", index_name)
                return True
            return False
        except Exception as exc:
            raise IntegrationError(f"Failed to ensure index {index_name}: {exc}") from exc

    # ── Document operations ───────────────────────────────────────────

    def index_document(self, index_name: str, doc_id: str, body: dict) -> dict:
        try:
            return self._client.index(index=index_name, id=doc_id, body=body, refresh="wait_for")
        except Exception as exc:
            raise IntegrationError(f"Failed to index document {doc_id}: {exc}") from exc

    def bulk_index(self, index_name: str, documents: list[dict]) -> dict:
        if not documents:
            return {"indexed": 0}
        actions = []
        for doc in documents:
            doc_id = doc.pop("_id", None)
            actions.append({"index": {"_index": index_name, "_id": doc_id}})
            actions.append(doc)
        try:
            result = self._client.bulk(body=actions, refresh="wait_for")
            return {"indexed": len(documents), "errors": result.get("errors", False)}
        except Exception as exc:
            raise IntegrationError(f"Bulk index failed: {exc}") from exc

    def search(self, index_name: str, query: dict, size: int = 20) -> list[dict]:
        try:
            result = self._client.search(index=index_name, body=query, size=size)
            return [hit["_source"] for hit in result["hits"]["hits"]]
        except Exception as exc:
            raise IntegrationError(f"Search failed on {index_name}: {exc}") from exc

    def delete_document(self, index_name: str, doc_id: str) -> dict:
        try:
            return self._client.delete(index=index_name, id=doc_id, refresh="wait_for")
        except Exception as exc:
            raise IntegrationError(f"Delete failed for {doc_id}: {exc}") from exc

    # ── Health ────────────────────────────────────────────────────────

    def health(self) -> dict[str, Any]:
        try:
            return self._client.cluster.health()
        except Exception as exc:
            raise IntegrationError(f"OpenSearch health check failed: {exc}") from exc
