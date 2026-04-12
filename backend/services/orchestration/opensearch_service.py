"""OpenSearch index management and search service.

Index design
────────────
- ``newsintel-articles``  — full-text search + faceted queries on articles.
- ``newsintel-events``    — event search with type/location/confidence facets.

All writes go through this service.  The pipeline calls
``IndexingOrchestrationService`` which delegates here.
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.conf import settings

from services.integrations.opensearch_adapter import OpenSearchAdapter

logger = logging.getLogger(__name__)

# ── Index names ────────────────────────────────────────────────────────────────

ARTICLE_INDEX = "newsintel-articles"
EVENT_INDEX = "newsintel-events"

# ── Index mappings ─────────────────────────────────────────────────────────────

ARTICLE_MAPPING: dict[str, Any] = {
    "settings": {
        "number_of_shards": 2,
        "number_of_replicas": 1,
        "analysis": {
            "analyzer": {
                "content_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "stop", "snowball"],
                },
            },
        },
    },
    "mappings": {
        "properties": {
            "article_id": {"type": "integer"},
            "title": {"type": "text", "analyzer": "content_analyzer", "fields": {"raw": {"type": "keyword"}}},
            "content": {"type": "text", "analyzer": "content_analyzer"},
            "url": {"type": "keyword"},
            "author": {"type": "keyword"},
            "source_id": {"type": "integer"},
            "source_name": {"type": "keyword"},
            "source_country": {"type": "keyword"},
            "source_type": {"type": "keyword"},
            "story_id": {"type": "integer"},
            "story_title": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
            "event_id": {"type": "integer"},
            "event_type": {"type": "keyword"},
            "published_at": {"type": "date"},
            "quality_score": {"type": "float"},
            "importance_score": {"type": "float"},
            "is_duplicate": {"type": "boolean"},
            "entity_names": {"type": "keyword"},
            "entity_types": {"type": "keyword"},
            "matched_topics": {"type": "keyword"},
            "matched_rule_labels": {"type": "keyword"},
            "content_hash": {"type": "keyword"},
            "indexed_at": {"type": "date"},
        },
    },
}

EVENT_MAPPING: dict[str, Any] = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 1,
    },
    "mappings": {
        "properties": {
            "event_id": {"type": "integer"},
            "title": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
            "description": {"type": "text"},
            "event_type": {"type": "keyword"},
            "location_name": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
            "location_country": {"type": "keyword"},
            "location": {"type": "geo_point"},
            "story_count": {"type": "integer"},
            "source_count": {"type": "integer"},
            "confidence_score": {"type": "float"},
            "geo_confidence": {"type": "float"},
            "conflict_flag": {"type": "boolean"},
            "importance_score": {"type": "float"},
            "first_reported_at": {"type": "date"},
            "last_reported_at": {"type": "date"},
            "indexed_at": {"type": "date"},
        },
    },
}


class OpenSearchService:
    """High-level search service wrapping the low-level adapter."""

    def __init__(self):
        self._adapter = OpenSearchAdapter()

    # ── Index bootstrap ───────────────────────────────────────────

    def ensure_indices(self) -> None:
        """Create indices if they don't exist.  Safe to call on every boot."""
        self._adapter.ensure_index(ARTICLE_INDEX, ARTICLE_MAPPING)
        self._adapter.ensure_index(EVENT_INDEX, EVENT_MAPPING)
        logger.info("OpenSearch indices ensured")

    # ── Article indexing ──────────────────────────────────────────

    def index_article(self, article) -> None:
        """Index a single Article into OpenSearch."""
        doc = self._article_to_doc(article)
        self._adapter.index_document(
            ARTICLE_INDEX,
            doc_id=str(article.id),
            body=doc,
        )

    def bulk_index_articles(self, articles) -> dict:
        """Bulk-index a batch of Articles."""
        docs = []
        for article in articles:
            doc = self._article_to_doc(article)
            doc["_id"] = str(article.id)
            docs.append(doc)
        return self._adapter.bulk_index(ARTICLE_INDEX, docs)

    # ── Event indexing ────────────────────────────────────────────

    def index_event(self, event) -> None:
        """Index a single Event into OpenSearch."""
        doc = self._event_to_doc(event)
        self._adapter.index_document(
            EVENT_INDEX,
            doc_id=str(event.id),
            body=doc,
        )

    # ── Search: Articles ──────────────────────────────────────────

    def search_articles(
        self,
        q: str,
        *,
        source_name: str | None = None,
        event_type: str | None = None,
        min_quality: float | None = None,
        min_importance: float | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        size: int = 20,
    ) -> list[dict]:
        """Full-text search across articles with optional facet filters."""
        must: list[dict] = []
        filters: list[dict] = []

        if q:
            must.append({
                "multi_match": {
                    "query": q,
                    "fields": ["title^3", "content", "story_title", "entity_names^2"],
                    "type": "cross_fields",
                    "operator": "and",
                },
            })

        # Exclude duplicates by default
        filters.append({"term": {"is_duplicate": False}})

        if source_name:
            filters.append({"term": {"source_name": source_name}})
        if event_type:
            filters.append({"term": {"event_type": event_type}})
        if min_quality is not None:
            filters.append({"range": {"quality_score": {"gte": min_quality}}})
        if min_importance is not None:
            filters.append({"range": {"importance_score": {"gte": min_importance}}})
        if from_date or to_date:
            date_range: dict[str, Any] = {}
            if from_date:
                date_range["gte"] = from_date
            if to_date:
                date_range["lte"] = to_date
            filters.append({"range": {"published_at": date_range}})

        query = {
            "query": {
                "bool": {
                    "must": must or [{"match_all": {}}],
                    "filter": filters,
                },
            },
            "sort": [
                {"_score": "desc"},
                {"published_at": "desc"},
            ],
        }

        return self._adapter.search(ARTICLE_INDEX, query, size=size)

    # ── Search: Events ────────────────────────────────────────────

    def search_events(
        self,
        q: str,
        *,
        event_type: str | None = None,
        country: str | None = None,
        conflict_only: bool = False,
        min_confidence: float | None = None,
        size: int = 20,
    ) -> list[dict]:
        """Full-text search across events."""
        must: list[dict] = []
        filters: list[dict] = []

        if q:
            must.append({
                "multi_match": {
                    "query": q,
                    "fields": ["title^3", "description", "location_name^2"],
                    "type": "cross_fields",
                    "operator": "and",
                },
            })

        if event_type:
            filters.append({"term": {"event_type": event_type}})
        if country:
            filters.append({"term": {"location_country": country}})
        if conflict_only:
            filters.append({"term": {"conflict_flag": True}})
        if min_confidence is not None:
            filters.append({"range": {"confidence_score": {"gte": min_confidence}}})

        query = {
            "query": {
                "bool": {
                    "must": must or [{"match_all": {}}],
                    "filter": filters,
                },
            },
            "sort": [
                {"_score": "desc"},
                {"last_reported_at": "desc"},
            ],
        }

        return self._adapter.search(EVENT_INDEX, query, size=size)

    # ── Document builders ─────────────────────────────────────────

    def _article_to_doc(self, article) -> dict:
        """Convert Article ORM instance to an OpenSearch document."""
        entity_names: list[str] = []
        entity_types: list[str] = []
        try:
            for ae in article.article_entities.select_related("entity").all():
                entity_names.append(ae.entity.name)
                entity_types.append(ae.entity.entity_type)
        except Exception:
            pass

        matched_topics: list[str] = []
        try:
            matched_topics = list(article.matched_topics.values_list("name", flat=True))
        except Exception:
            pass

        story = getattr(article, "story", None)
        event_id = None
        event_type = None
        if story and story.event_id:
            event_id = story.event_id
            try:
                event_type = story.event.event_type
            except Exception:
                pass

        return {
            "article_id": article.id,
            "title": article.title,
            "content": (article.content or "")[:10000],
            "url": article.url,
            "author": article.author,
            "source_id": article.source_id,
            "source_name": article.source.name if article.source else "",
            "source_country": article.source.country if article.source else "",
            "source_type": article.source.source_type if article.source else "",
            "story_id": article.story_id,
            "story_title": story.title if story else "",
            "event_id": event_id,
            "event_type": event_type,
            "published_at": article.published_at.isoformat() if article.published_at else None,
            "quality_score": float(article.quality_score),
            "importance_score": float(article.importance_score),
            "is_duplicate": article.is_duplicate,
            "entity_names": entity_names,
            "entity_types": list(set(entity_types)),
            "matched_topics": matched_topics,
            "matched_rule_labels": article.matched_rule_labels or [],
            "content_hash": article.content_hash,
            "indexed_at": datetime.utcnow().isoformat(),
        }

    def _event_to_doc(self, event) -> dict:
        """Convert Event ORM instance to an OpenSearch document."""
        location = None
        if event.location_lat is not None and event.location_lon is not None:
            location = {
                "lat": float(event.location_lat),
                "lon": float(event.location_lon),
            }

        return {
            "event_id": event.id,
            "title": event.title,
            "description": (event.description or "")[:5000],
            "event_type": event.event_type,
            "location_name": event.location_name,
            "location_country": event.location_country,
            "location": location,
            "story_count": event.story_count,
            "source_count": event.source_count,
            "confidence_score": float(event.confidence_score),
            "geo_confidence": float(event.geo_confidence),
            "conflict_flag": event.conflict_flag,
            "importance_score": float(event.importance_score),
            "first_reported_at": event.first_reported_at.isoformat() if event.first_reported_at else None,
            "last_reported_at": event.last_reported_at.isoformat() if event.last_reported_at else None,
            "indexed_at": datetime.utcnow().isoformat(),
        }
