"""Analyst exploration endpoints — Event Explorer, Entity Explorer,
Graph traversal, Map clusters, Timeline, and full-text search via OpenSearch.

These are analyst-product endpoints that go beyond basic CRUD:
- Event Explorer: timeline, related events, source breakdown, geographic proximity
- Entity Explorer: co-occurrence network, articles, events
- Graph: neighborhood traversal via Neo4j
- Map: geo-clustered events and entities
- Timeline: chronological event feeds
- Search: full-text search delegating to OpenSearch
"""
from __future__ import annotations

import html
import logging
import re
from collections import Counter
from datetime import timedelta
from decimal import Decimal

from django.db.models import Avg, Count, F, Max, Min, Q
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from sources.models import Article, ArticleEntity, Entity, Event, Source, Story
from sources.serializers import (
    ArticleListSerializer,
    EntitySerializer,
    EventDetailSerializer,
    EventListSerializer,
    StoryListSerializer,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# EVENT EXPLORER
# ═══════════════════════════════════════════════════════════════════════════════


class EventExplorerViewSet(viewsets.ReadOnlyModelViewSet):
    """Rich event exploration beyond basic CRUD.

    GET /api/v1/explore/events/                — list events with enrichment
    GET /api/v1/explore/events/{id}/           — event detail
    GET /api/v1/explore/events/{id}/timeline/  — chronological timeline
    GET /api/v1/explore/events/{id}/sources/   — source breakdown
    GET /api/v1/explore/events/{id}/entities/  — top entities across all articles
    GET /api/v1/explore/events/{id}/related/   — related events
    GET /api/v1/explore/events/{id}/articles/  — all articles for this event
    GET /api/v1/explore/events/hotspots/       — geographic + type aggregations
    """

    queryset = Event.objects.order_by("-last_reported_at", "-updated_at")

    def get_serializer_class(self):
        if self.action == "retrieve":
            return EventDetailSerializer
        return EventListSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        event_type = self.request.query_params.get("event_type")
        country = self.request.query_params.get("country")
        conflict = self.request.query_params.get("conflict")
        min_confidence = self.request.query_params.get("min_confidence")
        from_date = self.request.query_params.get("from_date")
        to_date = self.request.query_params.get("to_date")
        min_sources = self.request.query_params.get("min_sources")

        if event_type:
            qs = qs.filter(event_type=event_type)
        if country:
            qs = qs.filter(location_country=country)
        if conflict and conflict.lower() in ("true", "1"):
            qs = qs.filter(conflict_flag=True)
        if min_confidence:
            qs = qs.filter(confidence_score__gte=min_confidence)
        if from_date:
            qs = qs.filter(first_reported_at__gte=from_date)
        if to_date:
            qs = qs.filter(last_reported_at__lte=to_date)
        if min_sources:
            qs = qs.filter(source_count__gte=min_sources)
        return qs

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        """Chronological timeline for an event from timeline_json + article dates."""
        event = self.get_object()
        entries = list(event.timeline_json or [])

        # Supplement with article publication timestamps
        articles = Article.objects.filter(
            story__event=event, is_duplicate=False
        ).values("id", "title", "published_at", "source__name").order_by("published_at")

        for a in articles:
            if a["published_at"]:
                entries.append({
                    "ts": a["published_at"].isoformat(),
                    "type": "article",
                    "summary": a["title"][:200],
                    "source": a["source__name"],
                    "article_id": a["id"],
                })

        entries.sort(key=lambda e: e.get("ts", ""))
        return Response({"event_id": event.id, "title": event.title, "entries": entries})

    @action(detail=True, methods=["get"])
    def sources(self, request, pk=None):
        """Source breakdown for an event — which sources contributed, trust scores."""
        event = self.get_object()
        source_stats = (
            Article.objects.filter(story__event=event, is_duplicate=False)
            .values(
                source_id=F("source__id"),
                source_name=F("source__name"),
                source_type=F("source__source_type"),
                country=F("source__country"),
                trust_score=F("source__trust_score"),
            )
            .annotate(
                article_count=Count("id"),
                avg_quality=Avg("quality_score"),
                earliest=Min("published_at"),
                latest=Max("published_at"),
            )
            .order_by("-article_count")
        )
        return Response({
            "event_id": event.id,
            "total_sources": source_stats.count(),
            "sources": list(source_stats),
        })

    @action(detail=True, methods=["get"])
    def entities(self, request, pk=None):
        """Top entities appearing across all articles for this event."""
        event = self.get_object()
        entity_agg = (
            ArticleEntity.objects.filter(
                article__story__event=event,
                article__is_duplicate=False,
            )
            .values(
                entity_id=F("entity__id"),
                name=F("entity__name"),
                canonical_name=F("entity__canonical_name"),
                entity_type=F("entity__entity_type"),
                entity_country=F("entity__country"),
            )
            .annotate(
                total_mentions=Count("id"),
                avg_relevance=Avg("relevance_score"),
                article_count=Count("article", distinct=True),
            )
            .order_by("-total_mentions")[:50]
        )
        return Response({
            "event_id": event.id,
            "entities": list(entity_agg),
        })

    @action(detail=True, methods=["get"])
    def related(self, request, pk=None):
        """Find events related by shared entities, location, or time proximity."""
        event = self.get_object()
        related_ids = set()

        # 1. Same country + similar timeframe (±7 days)
        if event.location_country:
            window = timedelta(days=7)
            geo_related = Event.objects.filter(
                location_country=event.location_country,
            ).exclude(id=event.id)
            if event.first_reported_at:
                geo_related = geo_related.filter(
                    first_reported_at__gte=event.first_reported_at - window,
                    first_reported_at__lte=(event.last_reported_at or event.first_reported_at) + window,
                )
            for eid in geo_related.values_list("id", flat=True)[:20]:
                related_ids.add(eid)

        # 2. Shared entities (top entities of this event also appear in other events)
        top_entity_ids = (
            ArticleEntity.objects.filter(article__story__event=event)
            .values_list("entity_id", flat=True)
            .distinct()[:20]
        )
        if top_entity_ids:
            entity_related = (
                Event.objects.filter(
                    stories__articles__article_entities__entity_id__in=list(top_entity_ids),
                )
                .exclude(id=event.id)
                .values_list("id", flat=True)
                .distinct()[:20]
            )
            for eid in entity_related:
                related_ids.add(eid)

        related_events = Event.objects.filter(id__in=related_ids).order_by("-last_reported_at")[:30]
        serializer = EventListSerializer(related_events, many=True)
        return Response({
            "event_id": event.id,
            "related_count": len(related_events),
            "events": serializer.data,
        })

    @action(detail=True, methods=["get"])
    def articles(self, request, pk=None):
        """All articles for this event, across all stories."""
        event = self.get_object()
        qs = (
            Article.objects.filter(story__event=event, is_duplicate=False)
            .select_related("source", "story")
            .order_by("-published_at")
        )
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = ArticleListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = ArticleListSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def hotspots(self, request):
        """Aggregate events by country + event_type for dashboard heatmaps."""
        from_date = request.query_params.get("from_date")
        to_date = request.query_params.get("to_date")

        qs = Event.objects.all()
        if from_date:
            qs = qs.filter(first_reported_at__gte=from_date)
        if to_date:
            qs = qs.filter(last_reported_at__lte=to_date)

        by_country = list(
            qs.exclude(location_country="")
            .values("location_country")
            .annotate(
                event_count=Count("id"),
                avg_importance=Avg("importance_score"),
                conflict_count=Count("id", filter=Q(conflict_flag=True)),
            )
            .order_by("-event_count")[:50]
        )

        by_type = list(
            qs.values("event_type")
            .annotate(event_count=Count("id"))
            .order_by("-event_count")
        )

        return Response({
            "by_country": by_country,
            "by_type": by_type,
            "total_events": qs.count(),
        })


# ═══════════════════════════════════════════════════════════════════════════════
# ENTITY EXPLORER
# ═══════════════════════════════════════════════════════════════════════════════


class EntityExplorerViewSet(viewsets.ReadOnlyModelViewSet):
    """Rich entity exploration.

    GET /api/v1/explore/entities/                     — list entities
    GET /api/v1/explore/entities/{id}/                — entity detail
    GET /api/v1/explore/entities/{id}/articles/       — articles mentioning entity
    GET /api/v1/explore/entities/{id}/events/         — events connected to entity
    GET /api/v1/explore/entities/{id}/co-occurrences/ — entities that co-occur
    GET /api/v1/explore/entities/{id}/timeline/       — entity mention timeline
    """

    queryset = Entity.objects.annotate(article_count=Count("article_entities")).order_by("-article_count")
    serializer_class = EntitySerializer

    def get_queryset(self):
        qs = super().get_queryset()
        entity_type = self.request.query_params.get("entity_type")
        country = self.request.query_params.get("country")
        q = self.request.query_params.get("q")
        min_articles = self.request.query_params.get("min_articles")

        if entity_type:
            qs = qs.filter(entity_type=entity_type)
        if country:
            qs = qs.filter(country=country)
        if q:
            qs = qs.filter(
                Q(name__icontains=q) | Q(canonical_name__icontains=q) | Q(normalized_name__icontains=q)
            )
        if min_articles:
            qs = qs.filter(article_count__gte=int(min_articles))
        return qs

    @action(detail=True, methods=["get"])
    def articles(self, request, pk=None):
        """Articles mentioning this entity, sorted by relevance."""
        entity = self.get_object()
        qs = (
            Article.objects.filter(
                article_entities__entity=entity,
                is_duplicate=False,
            )
            .select_related("source", "story")
            .order_by("-article_entities__relevance_score", "-published_at")
        )
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = ArticleListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = ArticleListSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def events(self, request, pk=None):
        """Events connected to this entity (via articles → stories → events)."""
        entity = self.get_object()
        event_ids = (
            Article.objects.filter(
                article_entities__entity=entity,
                story__event__isnull=False,
                is_duplicate=False,
            )
            .values_list("story__event_id", flat=True)
            .distinct()[:100]
        )
        events = Event.objects.filter(id__in=list(event_ids)).order_by("-last_reported_at")
        serializer = EventListSerializer(events, many=True)
        return Response({
            "entity_id": entity.id,
            "entity_name": entity.name,
            "events": serializer.data,
        })

    @action(detail=True, methods=["get"], url_path="co-occurrences")
    def co_occurrences(self, request, pk=None):
        """Entities that frequently co-occur with this entity in the same articles."""
        entity = self.get_object()
        article_ids = list(
            ArticleEntity.objects.filter(entity=entity)
            .values_list("article_id", flat=True)[:500]
        )
        if not article_ids:
            return Response({"entity_id": entity.id, "co_occurrences": []})

        co_entities = (
            ArticleEntity.objects.filter(article_id__in=article_ids)
            .exclude(entity=entity)
            .values(
                co_entity_id=F("entity__id"),
                co_entity_name=F("entity__name"),
                co_entity_type=F("entity__entity_type"),
                co_entity_country=F("entity__country"),
            )
            .annotate(
                shared_articles=Count("article", distinct=True),
                avg_relevance=Avg("relevance_score"),
            )
            .order_by("-shared_articles")[:30]
        )
        return Response({
            "entity_id": entity.id,
            "entity_name": entity.name,
            "co_occurrences": list(co_entities),
        })

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        """Chronological timeline of articles mentioning this entity."""
        entity = self.get_object()
        mentions = (
            Article.objects.filter(
                article_entities__entity=entity,
                is_duplicate=False,
                published_at__isnull=False,
            )
            .values("id", "title", "published_at", "source__name", "importance_score")
            .order_by("published_at")[:200]
        )
        entries = [
            {
                "ts": m["published_at"].isoformat(),
                "article_id": m["id"],
                "title": m["title"][:200],
                "source": m["source__name"],
                "importance_score": float(m["importance_score"]),
            }
            for m in mentions
        ]
        return Response({
            "entity_id": entity.id,
            "entity_name": entity.name,
            "entries": entries,
        })


# ═══════════════════════════════════════════════════════════════════════════════
# GRAPH EXPLORATION (Neo4j)
# ═══════════════════════════════════════════════════════════════════════════════


@api_view(["GET"])
def graph_neighbors(request):
    """Traverse the knowledge graph from a given node.

    GET /api/v1/explore/graph/neighbors/?label=Entity&id=42&depth=1

    Returns the immediate neighborhood of a node in the graph.
    """
    label = request.query_params.get("label")
    node_id = request.query_params.get("id")
    depth = min(int(request.query_params.get("depth", "1")), 3)

    if not label or not node_id:
        return Response(
            {"error": "label and id are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    allowed_labels = {"Source", "Article", "Story", "Event", "Entity", "Topic", "Location"}
    if label not in allowed_labels:
        return Response(
            {"error": f"label must be one of: {', '.join(sorted(allowed_labels))}"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    id_field = _label_id_field(label)
    try:
        node_id_val = int(node_id) if id_field != "name" else node_id
    except ValueError:
        return Response({"error": "id must be an integer for this label"}, status=status.HTTP_400_BAD_REQUEST)

    from services.integrations.neo4j_adapter import Neo4jAdapter

    try:
        adapter = Neo4jAdapter()
        cypher = (
            f"MATCH path = (n:{label} {{{id_field}: $nid}})-[*1..{depth}]-(m) "
            "WITH n, m, relationships(path) AS rels "
            "UNWIND rels AS r "
            "RETURN DISTINCT "
            "  labels(startNode(r))[0] AS from_label, "
            "  properties(startNode(r)) AS from_props, "
            "  type(r) AS rel_type, "
            "  properties(r) AS rel_props, "
            "  labels(endNode(r))[0] AS to_label, "
            "  properties(endNode(r)) AS to_props "
            "LIMIT 200"
        )
        records = adapter.read_query(cypher, {"nid": node_id_val})
        adapter.close()
    except Exception as exc:
        logger.warning("Graph neighbors query failed: %s", exc, exc_info=True)
        return Response({"error": "Graph query failed"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    # Build deduplicated node + edge lists
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for rec in records:
        from_key = f"{rec['from_label']}:{_node_key(rec['from_props'], rec['from_label'])}"
        to_key = f"{rec['to_label']}:{_node_key(rec['to_props'], rec['to_label'])}"
        nodes[from_key] = {"label": rec["from_label"], **_safe_props(rec["from_props"])}
        nodes[to_key] = {"label": rec["to_label"], **_safe_props(rec["to_props"])}
        edges.append({
            "from": from_key,
            "to": to_key,
            "type": rec["rel_type"],
            "properties": _safe_props(rec.get("rel_props") or {}),
        })

    return Response({
        "root": f"{label}:{node_id}",
        "depth": depth,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": list(nodes.values()),
        "edges": edges,
    })


@api_view(["GET"])
def graph_shortest_path(request):
    """Find shortest path between two nodes.

    GET /api/v1/explore/graph/path/?from_label=Entity&from_id=1&to_label=Entity&to_id=2
    """
    from_label = request.query_params.get("from_label")
    from_id = request.query_params.get("from_id")
    to_label = request.query_params.get("to_label")
    to_id = request.query_params.get("to_id")

    if not all([from_label, from_id, to_label, to_id]):
        return Response(
            {"error": "from_label, from_id, to_label, to_id are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    from_id_field = _label_id_field(from_label)
    to_id_field = _label_id_field(to_label)

    try:
        from_id_val = int(from_id) if from_id_field != "name" else from_id
        to_id_val = int(to_id) if to_id_field != "name" else to_id
    except ValueError:
        return Response({"error": "Invalid id type"}, status=status.HTTP_400_BAD_REQUEST)

    from services.integrations.neo4j_adapter import Neo4jAdapter

    try:
        adapter = Neo4jAdapter()
        cypher = (
            f"MATCH path = shortestPath("
            f"(a:{from_label} {{{from_id_field}: $fid}})-[*..6]-"
            f"(b:{to_label} {{{to_id_field}: $tid}}))"
            " RETURN [n IN nodes(path) | {label: labels(n)[0], props: properties(n)}] AS nodes, "
            "        [r IN relationships(path) | {type: type(r), props: properties(r)}] AS rels"
        )
        records = adapter.read_query(cypher, {"fid": from_id_val, "tid": to_id_val})
        adapter.close()
    except Exception as exc:
        logger.warning("Graph shortest path failed: %s", exc, exc_info=True)
        return Response({"error": "Graph query failed"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    if not records:
        return Response({"path": None, "message": "No path found"})

    row = records[0]
    path_nodes = [
        {"label": n["label"], **_safe_props(n["props"])} for n in row["nodes"]
    ]
    path_rels = [
        {"type": r["type"], **_safe_props(r.get("props") or {})} for r in row["rels"]
    ]
    return Response({
        "path_length": len(path_rels),
        "nodes": path_nodes,
        "relationships": path_rels,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# MAP ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════


@api_view(["GET"])
def map_events(request):
    """Return geo-located events for map rendering.

    GET /api/v1/explore/map/events/?from_date=...&to_date=...&event_type=...
    """
    qs = Event.objects.filter(
        location_lat__isnull=False,
        location_lon__isnull=False,
    )

    event_type = request.query_params.get("event_type")
    country = request.query_params.get("country")
    from_date = request.query_params.get("from_date")
    to_date = request.query_params.get("to_date")
    conflict = request.query_params.get("conflict")
    min_importance = request.query_params.get("min_importance")

    if event_type:
        qs = qs.filter(event_type=event_type)
    if country:
        qs = qs.filter(location_country=country)
    if from_date:
        qs = qs.filter(first_reported_at__gte=from_date)
    if to_date:
        qs = qs.filter(last_reported_at__lte=to_date)
    if conflict and conflict.lower() in ("true", "1"):
        qs = qs.filter(conflict_flag=True)
    if min_importance:
        qs = qs.filter(importance_score__gte=min_importance)

    events = qs.values(
        "id", "title", "event_type", "location_name", "location_country",
        "location_lat", "location_lon", "importance_score", "confidence_score",
        "conflict_flag", "story_count", "source_count",
        "first_reported_at", "last_reported_at",
    ).order_by("-last_reported_at")[:500]

    features = []
    for e in events:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(e["location_lon"]), float(e["location_lat"])],
            },
            "properties": {
                "id": e["id"],
                "title": e["title"],
                "event_type": e["event_type"],
                "location_name": e["location_name"],
                "country": e["location_country"],
                "importance": float(e["importance_score"]),
                "confidence": float(e["confidence_score"]),
                "conflict": e["conflict_flag"],
                "stories": e["story_count"],
                "sources": e["source_count"],
                "first_reported": e["first_reported_at"].isoformat() if e["first_reported_at"] else None,
                "last_reported": e["last_reported_at"].isoformat() if e["last_reported_at"] else None,
            },
        })

    return Response({
        "type": "FeatureCollection",
        "features": features,
    })


@api_view(["GET"])
def map_entities(request):
    """Return geo-located entities for map rendering.

    GET /api/v1/explore/map/entities/?entity_type=location&country=...
    """
    qs = Entity.objects.filter(
        latitude__isnull=False,
        longitude__isnull=False,
    ).annotate(article_count=Count("article_entities"))

    entity_type = request.query_params.get("entity_type")
    country = request.query_params.get("country")
    min_articles = request.query_params.get("min_articles")

    if entity_type:
        qs = qs.filter(entity_type=entity_type)
    if country:
        qs = qs.filter(country=country)
    if min_articles:
        qs = qs.filter(article_count__gte=int(min_articles))

    entities = qs.values(
        "id", "name", "canonical_name", "entity_type", "country",
        "latitude", "longitude", "article_count",
    ).order_by("-article_count")[:500]

    features = []
    for e in entities:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(e["longitude"]), float(e["latitude"])],
            },
            "properties": {
                "id": e["id"],
                "name": e["name"],
                "canonical_name": e["canonical_name"],
                "entity_type": e["entity_type"],
                "country": e["country"],
                "articles": e["article_count"],
            },
        })

    return Response({
        "type": "FeatureCollection",
        "features": features,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# TIMELINE
# ═══════════════════════════════════════════════════════════════════════════════


@api_view(["GET"])
def global_timeline(request):
    """Global event + article timeline feed.

    GET /api/v1/explore/timeline/?from_date=...&to_date=...&event_type=...&limit=100
    """
    from_date = request.query_params.get("from_date")
    to_date = request.query_params.get("to_date")
    event_type = request.query_params.get("event_type")
    country = request.query_params.get("country")
    limit = min(int(request.query_params.get("limit", "100")), 500)

    # Event entries
    event_qs = Event.objects.filter(first_reported_at__isnull=False)
    if from_date:
        event_qs = event_qs.filter(first_reported_at__gte=from_date)
    if to_date:
        event_qs = event_qs.filter(last_reported_at__lte=to_date)
    if event_type:
        event_qs = event_qs.filter(event_type=event_type)
    if country:
        event_qs = event_qs.filter(location_country=country)

    entries: list[dict] = []
    for e in event_qs.order_by("-first_reported_at")[:limit]:
        entries.append({
            "ts": e.first_reported_at.isoformat(),
            "type": "event",
            "id": e.id,
            "title": e.title,
            "event_type": e.event_type,
            "location": e.location_name,
            "country": e.location_country,
            "importance": float(e.importance_score),
            "confidence": float(e.confidence_score),
            "conflict": e.conflict_flag,
            "stories": e.story_count,
            "sources": e.source_count,
        })

    entries.sort(key=lambda e: e["ts"], reverse=True)
    return Response({"count": len(entries), "entries": entries[:limit]})


# ═══════════════════════════════════════════════════════════════════════════════
# FULL-TEXT SEARCH (OpenSearch)
# ═══════════════════════════════════════════════════════════════════════════════


@api_view(["GET"])
def search_articles(request):
    """Full-text article search via OpenSearch.

    GET /api/v1/explore/search/articles/?q=explosion&source=...&from_date=...
    """
    raw_q = request.query_params.get("q", "")
    q = re.sub(r"<[^>]*>", "", raw_q).strip()
    source_name = request.query_params.get("source")
    event_type = request.query_params.get("event_type")
    min_quality = request.query_params.get("min_quality")
    min_importance = request.query_params.get("min_importance")
    from_date = request.query_params.get("from_date")
    to_date = request.query_params.get("to_date")
    size = min(int(request.query_params.get("size", "20")), 100)

    from services.orchestration.opensearch_service import OpenSearchService

    try:
        svc = OpenSearchService()
        results = svc.search_articles(
            q,
            source_name=source_name,
            event_type=event_type,
            min_quality=float(min_quality) if min_quality else None,
            min_importance=float(min_importance) if min_importance else None,
            from_date=from_date,
            to_date=to_date,
            size=size,
        )
    except Exception as exc:
        logger.warning("OpenSearch article search failed: %s", exc, exc_info=True)
        return Response({"error": "Search unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    return Response({"query": q, "count": len(results), "results": results})


@api_view(["GET"])
def search_events(request):
    """Full-text event search via OpenSearch.

    GET /api/v1/explore/search/events/?q=protest&country=US&conflict=true
    """
    raw_q = request.query_params.get("q", "")
    q = re.sub(r"<[^>]*>", "", raw_q).strip()
    event_type = request.query_params.get("event_type")
    country = request.query_params.get("country")
    conflict_only = request.query_params.get("conflict", "").lower() in ("true", "1")
    min_confidence = request.query_params.get("min_confidence")
    size = min(int(request.query_params.get("size", "20")), 100)

    from services.orchestration.opensearch_service import OpenSearchService

    try:
        svc = OpenSearchService()
        results = svc.search_events(
            q,
            event_type=event_type,
            country=country,
            conflict_only=conflict_only,
            min_confidence=float(min_confidence) if min_confidence else None,
            size=size,
        )
    except Exception as exc:
        logger.warning("OpenSearch event search failed: %s", exc, exc_info=True)
        return Response({"error": "Search unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    return Response({"query": q, "count": len(results), "results": results})


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════


def _label_id_field(label: str) -> str:
    """Return the id property name for a given Neo4j node label."""
    return {
        "Source": "source_id",
        "Article": "article_id",
        "Story": "story_id",
        "Event": "event_id",
        "Entity": "entity_id",
        "Topic": "topic_id",
        "Location": "name",
    }.get(label, "id")


def _node_key(props: dict, label: str) -> str:
    """Return a string key for uniquely identifying a node in results."""
    id_field = _label_id_field(label)
    return str(props.get(id_field, props.get("name", id(props))))


def _safe_props(props: dict) -> dict:
    """Ensure all values are JSON-serializable."""
    safe = {}
    for k, v in props.items():
        if isinstance(v, Decimal):
            safe[k] = float(v)
        else:
            safe[k] = v
    return safe
