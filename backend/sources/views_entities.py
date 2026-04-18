"""Unified Entity Explorer API — merges basic CRUD with analyst exploration.

Replaces the fragmented EntityViewSet (sources/views_api.py) and
EntityExplorerViewSet (sources/views_explore.py) into a single cohesive API:

    GET    /api/v1/entities/                          — list entities (filterable)
    GET    /api/v1/entities/{id}/                     — entity detail
    GET    /api/v1/entities/{id}/articles/            — articles mentioning entity
    GET    /api/v1/entities/{id}/events/              — events connected to entity
    GET    /api/v1/entities/{id}/co-occurrences/      — co-occurring entities
    GET    /api/v1/entities/{id}/timeline/            — chronological mentions
    GET    /api/v1/entities/{id}/mentions/            — article mention details
    GET    /api/v1/entities/{id}/network/             — entity network from Neo4j
    POST   /api/v1/entities/{id}/attach-case/         — link entity to a case

Entity Intelligence Layer:
    GET    /api/v1/entities/{id}/relationships/       — stored scored relationships
    GET    /api/v1/entities/{id}/graph-data/          — D3-ready graph for this entity
    GET    /api/v1/entities/{id}/influence/           — influence score + signals
"""
from __future__ import annotations

import logging

from django.db.models import Avg, Count, F, Q
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Article, ArticleEntity, Entity, EntityInfluenceScore, EntityRelationship, EntitySignal, Event
from .serializers import (
    ArticleListSerializer,
    EntitySerializer,
    EventListSerializer,
)

logger = logging.getLogger(__name__)


class EntityViewSet(viewsets.ReadOnlyModelViewSet):
    """Unified entity API — combines CRUD listing with analyst exploration."""

    queryset = Entity.objects.annotate(
        article_count=Count("article_entities"),
    ).order_by("-article_count")
    serializer_class = EntitySerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "canonical_name", "normalized_name"]
    ordering_fields = ["name", "entity_type", "article_count", "created_at"]
    ordering = ["-article_count"]

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
                Q(name__icontains=q)
                | Q(canonical_name__icontains=q)
                | Q(normalized_name__icontains=q)
            )
        if min_articles:
            qs = qs.filter(article_count__gte=int(min_articles))
        return qs

    # ── Articles ───────────────────────────────────────────────────

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

    # ── Events ─────────────────────────────────────────────────────

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

    # ── Co-occurrences ─────────────────────────────────────────────

    @action(detail=True, methods=["get"], url_path="co-occurrences")
    def co_occurrences(self, request, pk=None):
        """Entities that frequently co-occur with this entity in articles."""
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

    # ── Timeline ───────────────────────────────────────────────────

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

    # ── Mentions ───────────────────────────────────────────────────

    @action(detail=True, methods=["get"])
    def mentions(self, request, pk=None):
        """Detailed mention data — relevance, count, and context per article."""
        entity = self.get_object()
        qs = (
            ArticleEntity.objects.filter(entity=entity)
            .select_related("article", "article__source")
            .order_by("-relevance_score", "-article__published_at")
        )

        page = self.paginate_queryset(qs)
        items = page if page is not None else qs[:100]

        data = [
            {
                "article_id": ae.article.id,
                "article_title": ae.article.title[:200],
                "source": ae.article.source.name if ae.article.source else None,
                "published_at": ae.article.published_at.isoformat() if ae.article.published_at else None,
                "relevance_score": float(ae.relevance_score),
                "mention_count": ae.mention_count,
                "context_snippet": ae.context_snippet or "",
            }
            for ae in items
        ]

        if page is not None:
            return self.get_paginated_response(data)
        return Response({
            "entity_id": entity.id,
            "entity_name": entity.name,
            "mentions": data,
        })

    # ── Network (Neo4j) ───────────────────────────────────────────

    @action(detail=True, methods=["get"])
    def network(self, request, pk=None):
        """Entity relationship network from Neo4j knowledge graph."""
        entity = self.get_object()
        depth = min(int(request.query_params.get("depth", "1")), 3)

        from sources.views_explore import _label_id_field, _node_key, _safe_props

        try:
            from services.integrations.neo4j_adapter import Neo4jAdapter

            adapter = Neo4jAdapter()
            cypher = (
                f"MATCH path = (n:Entity {{entity_id: $eid}})-[*1..{depth}]-(m) "
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
            records = adapter.read_query(cypher, {"eid": entity.id})
            adapter.close()
        except Exception as exc:
            logger.warning("Entity network query failed: %s", exc, exc_info=True)
            return Response(
                {"error": "Graph query failed"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

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
            "entity_id": entity.id,
            "entity_name": entity.name,
            "depth": depth,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "nodes": list(nodes.values()),
            "edges": edges,
        })

    # ── Explain ────────────────────────────────────────────────────

    @action(detail=True, methods=["get"])
    def explain(self, request, pk=None):
        """Explainability breakdown for an entity: importance factors,
        source diversity, top events, and co-occurring entities."""
        entity = self.get_object()

        # Importance factors
        article_count = ArticleEntity.objects.filter(entity=entity).count()
        event_ids = (
            Article.objects.filter(
                article_entities__entity=entity,
                is_duplicate=False,
                story__event__isnull=False,
            )
            .values_list("story__event_id", flat=True)
            .distinct()
        )
        event_count = len(set(event_ids))

        co_occ = (
            ArticleEntity.objects.filter(
                article__in=ArticleEntity.objects.filter(entity=entity).values("article"),
            )
            .exclude(entity=entity)
            .values("entity")
            .distinct()
            .count()
        )

        avg_rel = ArticleEntity.objects.filter(entity=entity).aggregate(
            avg=Avg("relevance_score"),
        )["avg"] or 0

        # Source diversity
        source_info = (
            Article.objects.filter(
                article_entities__entity=entity,
                is_duplicate=False,
            )
            .values_list("source__name", "source__source_type", "source__country")
            .distinct()
        )
        unique_sources = len(set(s[0] for s in source_info if s[0]))
        source_types = sorted(set(s[1] for s in source_info if s[1]))
        countries = sorted(set(s[2] for s in source_info if s[2]))

        mention_diversity = min(unique_sources / 10, 1.0) if unique_sources else 0

        # Top events
        top_events = list(
            Event.objects.filter(id__in=event_ids)
            .order_by("-importance_score")
            .values("id", "title", "event_type", "importance_score")[:5]
        )
        for e in top_events:
            e["importance"] = float(e.pop("importance_score"))

        # Top co-occurring entities
        top_co = list(
            ArticleEntity.objects.filter(
                article__in=ArticleEntity.objects.filter(entity=entity).values("article"),
            )
            .exclude(entity=entity)
            .values("entity_id", name=F("entity__name"), entity_type=F("entity__entity_type"))
            .annotate(shared_articles=Count("article", distinct=True))
            .order_by("-shared_articles")[:5]
        )
        top_co_entities = [
            {"id": c["entity_id"], "name": c["name"], "entity_type": c["entity_type"], "shared_articles": c["shared_articles"]}
            for c in top_co
        ]

        return Response({
            "entity_id": entity.id,
            "entity_name": entity.name,
            "entity_type": entity.entity_type,
            "description": getattr(entity, "description", "") or "",
            "importance_factors": {
                "article_count": article_count,
                "event_count": event_count,
                "co_occurrence_count": co_occ,
                "mention_diversity": round(mention_diversity, 3),
                "avg_relevance": round(float(avg_rel), 3),
            },
            "source_diversity": {
                "unique_sources": unique_sources,
                "source_types": source_types,
                "countries": countries,
            },
            "top_events": top_events,
            "top_co_entities": top_co_entities,
        })

    # ── Attach to case ─────────────────────────────────────────────

    @action(detail=True, methods=["post"], url_path="attach-case")
    def attach_case(self, request, pk=None):
        """Link this entity to an investigation case."""
        entity = self.get_object()
        case_id = request.data.get("case_id")
        notes = request.data.get("notes", "")

        if not case_id:
            return Response(
                {"error": "case_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from cases.models import Case, CaseEntity

        try:
            case = Case.objects.get(id=case_id)
        except Case.DoesNotExist:
            return Response(
                {"error": "Case not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        obj, created = CaseEntity.objects.get_or_create(
            case=case, entity=entity,
            defaults={
                "notes": notes,
                "added_by": request.user if request.user.is_authenticated else None,
            },
        )
        return Response(
            {
                "case_id": case.id,
                "entity_id": entity.id,
                "created": created,
                "case_entity_id": obj.id,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    # ── Relationships (Intelligence Layer) ────────────────────────

    @action(detail=True, methods=["get"])
    def relationships(self, request, pk=None):
        """Stored, scored co-occurrence relationships for this entity.

        Query params:
          min_strength  float  default 0.05
          type          str    filter by relationship_type
          ordering      str    strength_score | last_seen_at | co_occurrence_count
          page / page_size
        """
        entity = self.get_object()
        min_strength = float(request.query_params.get("min_strength", "0.05"))
        rel_type = request.query_params.get("type")
        ordering = request.query_params.get("ordering", "-strength_score")

        # Validate ordering param to prevent injection
        allowed_orderings = {
            "strength_score", "-strength_score",
            "last_seen_at", "-last_seen_at",
            "co_occurrence_count", "-co_occurrence_count",
        }
        if ordering not in allowed_orderings:
            ordering = "-strength_score"

        from django.db.models import Q as DQ
        qs = (
            EntityRelationship.objects
            .filter(
                DQ(entity_a=entity) | DQ(entity_b=entity),
                strength_score__gte=min_strength,
            )
            .select_related("entity_a", "entity_b")
            .order_by(ordering)
        )
        if rel_type:
            qs = qs.filter(relationship_type=rel_type)

        page = self.paginate_queryset(qs)
        items = page if page is not None else list(qs[:50])

        data = []
        for rel in items:
            other = rel.entity_b if rel.entity_a_id == entity.id else rel.entity_a
            data.append({
                "relationship_id":    rel.id,
                "entity_id":          other.id,
                "entity_name":        other.canonical_name or other.name,
                "entity_type":        other.entity_type,
                "entity_country":     other.country,
                "relationship_type":  rel.relationship_type,
                "strength_score":     float(rel.strength_score),
                "confidence":         float(rel.confidence),
                "recency_score":      float(rel.recency_score),
                "source_diversity":   float(rel.source_diversity_score),
                "co_occurrence_count": rel.co_occurrence_count,
                "growth_rate":        float(rel.growth_rate),
                "last_seen_at":       rel.last_seen_at.isoformat() if rel.last_seen_at else None,
                "first_seen_at":      rel.first_seen_at.isoformat() if rel.first_seen_at else None,
            })

        if page is not None:
            return self.get_paginated_response(data)
        return Response({
            "entity_id":   entity.id,
            "entity_name": entity.canonical_name or entity.name,
            "relationships": data,
        })

    @action(detail=True, methods=["get"], url_path="graph-data")
    def graph_data(self, request, pk=None):
        """D3-ready graph payload centred on this entity.

        Returns nodes + edges within ``depth`` hops.  Depth is capped at 2.
        """
        entity = self.get_object()
        depth = min(int(request.query_params.get("depth", "1")), 2)
        min_strength = float(request.query_params.get("min_strength", "0.05"))

        from django.db.models import Q as DQ

        # Hop 1: direct relationships
        rels_1 = list(
            EntityRelationship.objects
            .filter(
                DQ(entity_a=entity) | DQ(entity_b=entity),
                strength_score__gte=min_strength,
            )
            .select_related("entity_a", "entity_b")
            .order_by("-strength_score")[:50]
        )

        neighbour_ids = set()
        for rel in rels_1:
            neighbour_ids.add(rel.entity_a_id)
            neighbour_ids.add(rel.entity_b_id)
        neighbour_ids.discard(entity.id)

        all_rels = list(rels_1)

        if depth >= 2 and neighbour_ids:
            rels_2 = list(
                EntityRelationship.objects
                .filter(
                    DQ(entity_a_id__in=neighbour_ids) | DQ(entity_b_id__in=neighbour_ids),
                    strength_score__gte=min_strength + 0.05,
                )
                .exclude(DQ(entity_a=entity) | DQ(entity_b=entity))
                .select_related("entity_a", "entity_b")
                .order_by("-strength_score")[:80]
            )
            all_rels.extend(rels_2)
            for rel in rels_2:
                neighbour_ids.add(rel.entity_a_id)
                neighbour_ids.add(rel.entity_b_id)

        # Build nodes dict
        all_entity_ids = neighbour_ids | {entity.id}
        entities = {
            e.id: e
            for e in Entity.objects.filter(id__in=all_entity_ids)
        }
        influence = {
            inf.entity_id: inf
            for inf in EntityInfluenceScore.objects.filter(entity_id__in=all_entity_ids)
        }

        nodes = []
        for eid, ent in entities.items():
            inf = influence.get(eid)
            nodes.append({
                "id":          eid,
                "label":       ent.canonical_name or ent.name,
                "type":        ent.entity_type,
                "country":     ent.country,
                "is_root":     eid == entity.id,
                "influence":   float(inf.influence_score) if inf else 0.0,
                "mentions_7d": inf.mentions_last_7d if inf else 0,
                "growth_flag": inf.growth_flag if inf else False,
            })

        edges = []
        seen_pairs: set[tuple[int, int]] = set()
        for rel in all_rels:
            pair = (rel.entity_a_id, rel.entity_b_id)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            edges.append({
                "source":          rel.entity_a_id,
                "target":          rel.entity_b_id,
                "type":            rel.relationship_type,
                "strength":        float(rel.strength_score),
                "co_occurrences":  rel.co_occurrence_count,
                "last_seen_at":    rel.last_seen_at.isoformat() if rel.last_seen_at else None,
                "growth_rate":     float(rel.growth_rate),
            })

        return Response({
            "entity_id":    entity.id,
            "entity_name":  entity.canonical_name or entity.name,
            "depth":        depth,
            "node_count":   len(nodes),
            "edge_count":   len(edges),
            "nodes":        nodes,
            "edges":        edges,
        })

    @action(detail=True, methods=["get"])
    def influence(self, request, pk=None):
        """Influence score, mention velocity, and recent signals for this entity."""
        entity = self.get_object()

        try:
            inf = EntityInfluenceScore.objects.get(entity=entity)
            inf_data = {
                "degree_centrality":  float(inf.degree_centrality),
                "weighted_degree":    float(inf.weighted_degree),
                "mentions_last_24h":  inf.mentions_last_24h,
                "mentions_last_7d":   inf.mentions_last_7d,
                "mentions_last_30d":  inf.mentions_last_30d,
                "velocity_score":     float(inf.velocity_score),
                "growth_flag":        inf.growth_flag,
                "influence_rank":     inf.influence_rank,
                "influence_score":    float(inf.influence_score),
                "scored_at":          inf.scored_at.isoformat(),
            }
        except EntityInfluenceScore.DoesNotExist:
            inf_data = None

        signals = list(
            EntitySignal.objects
            .filter(entity=entity)
            .order_by("-created_at")
            .values(
                "id", "signal_type", "severity", "title",
                "description", "metadata", "is_read", "created_at",
            )[:10]
        )
        for s in signals:
            s["created_at"] = s["created_at"].isoformat()

        rel_count = EntityRelationship.objects.filter(
            __import__("django.db.models", fromlist=["Q"]).Q(entity_a=entity)
            | __import__("django.db.models", fromlist=["Q"]).Q(entity_b=entity)
        ).count()

        return Response({
            "entity_id":         entity.id,
            "entity_name":       entity.canonical_name or entity.name,
            "relationship_count": rel_count,
            "influence":         inf_data,
            "recent_signals":    signals,
        })
