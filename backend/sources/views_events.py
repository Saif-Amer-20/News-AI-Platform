"""Unified Event Explorer API — merges basic CRUD with analyst exploration.

Replaces the fragmented EventViewSet (sources/views_api.py) and
EventExplorerViewSet (sources/views_explore.py) into a single cohesive API:

    GET    /api/v1/events/                         — list events (filterable)
    GET    /api/v1/events/{id}/                    — event detail with stories
    GET    /api/v1/events/conflicts/               — events with conflict flag
    GET    /api/v1/events/hotspots/                — aggregated heatmap data
    GET    /api/v1/events/{id}/timeline/           — event timeline + articles
    GET    /api/v1/events/{id}/sources/            — source breakdown
    GET    /api/v1/events/{id}/entities/           — top entities in this event
    GET    /api/v1/events/{id}/related/            — geographically/entity-related
    GET    /api/v1/events/{id}/articles/           — all non-duplicate articles
    GET    /api/v1/events/{id}/stories/            — stories under this event
    GET    /api/v1/events/{id}/explain/            — how this event was inferred
    POST   /api/v1/events/{id}/attach-case/        — link event to a case
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import timedelta
from decimal import Decimal

from django.db.models import Avg, Count, F, Max, Min, Q
from django.utils import timezone
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Article, ArticleEntity, Entity, Event, Source, Story
from .serializers import (
    ArticleListSerializer,
    EntitySerializer,
    EventDetailSerializer,
    EventListSerializer,
    StoryListSerializer,
)

logger = logging.getLogger(__name__)


class EventViewSet(viewsets.ReadOnlyModelViewSet):
    """Unified event API — combines CRUD listing with analyst exploration."""

    queryset = Event.objects.order_by("-last_reported_at", "-updated_at")
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["title", "description", "location_name"]
    ordering_fields = [
        "confidence_score", "importance_score", "story_count",
        "source_count", "last_reported_at",
    ]
    ordering = ["-last_reported_at"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return EventDetailSerializer
        return EventListSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        event_type = self.request.query_params.get("event_type")
        country = self.request.query_params.get("country")
        conflict_only = self.request.query_params.get("conflict")
        min_confidence = self.request.query_params.get("min_confidence")
        min_importance = self.request.query_params.get("min_importance")
        from_date = self.request.query_params.get("from_date")
        to_date = self.request.query_params.get("to_date")
        min_sources = self.request.query_params.get("min_sources")

        if event_type:
            qs = qs.filter(event_type=event_type)
        if country:
            qs = qs.filter(location_country=country)
        if conflict_only and conflict_only.lower() in ("true", "1"):
            qs = qs.filter(conflict_flag=True)
        if min_confidence:
            qs = qs.filter(confidence_score__gte=min_confidence)
        if min_importance:
            qs = qs.filter(importance_score__gte=min_importance)
        if from_date:
            qs = qs.filter(first_reported_at__gte=from_date)
        if to_date:
            qs = qs.filter(last_reported_at__lte=to_date)
        if min_sources:
            qs = qs.filter(source_count__gte=int(min_sources))
        return qs

    # ── Conflict listing ───────────────────────────────────────────

    @action(detail=False, methods=["get"])
    def conflicts(self, request):
        """Events with conflict_flag=True."""
        qs = self.filter_queryset(self.get_queryset()).filter(conflict_flag=True)
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = EventListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = EventListSerializer(qs[:100], many=True)
        return Response(serializer.data)

    # ── Hotspots ───────────────────────────────────────────────────

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

    # ── Timeline ───────────────────────────────────────────────────

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        """Return the event's precomputed timeline + article timestamps."""
        event = self.get_object()

        # Precomputed timeline from the intelligence engine
        event_timeline = event.timeline_json or []

        # Article-level timeline entries
        article_entries = list(
            Article.objects.filter(
                story__event=event,
                is_duplicate=False,
                published_at__isnull=False,
            )
            .order_by("published_at")
            .values("id", "title", "published_at", "source__name", "importance_score")[:200]
        )
        for a in article_entries:
            if a["published_at"]:
                a["published_at"] = a["published_at"].isoformat()
            a["importance_score"] = float(a["importance_score"])

        return Response({
            "event_id": event.id,
            "event_title": event.title,
            "first_reported_at": event.first_reported_at.isoformat() if event.first_reported_at else None,
            "last_reported_at": event.last_reported_at.isoformat() if event.last_reported_at else None,
            "intelligence_timeline": event_timeline,
            "article_timeline": article_entries,
        })

    # ── Source breakdown ───────────────────────────────────────────

    @action(detail=True, methods=["get"])
    def sources(self, request, pk=None):
        """Which sources covered this event, with trust scores."""
        event = self.get_object()
        articles = (
            Article.objects.filter(story__event=event, is_duplicate=False)
            .select_related("source")
        )
        source_stats: dict[int, dict] = {}
        for a in articles:
            src = a.source
            if src.id not in source_stats:
                source_stats[src.id] = {
                    "source_id": src.id,
                    "name": src.name,
                    "source_type": src.source_type,
                    "country": src.country,
                    "trust_score": float(src.trust_score),
                    "article_count": 0,
                    "earliest": a.published_at,
                    "latest": a.published_at,
                }
            source_stats[src.id]["article_count"] += 1
            pa = a.published_at
            if pa:
                entry = source_stats[src.id]
                if entry["earliest"] is None or pa < entry["earliest"]:
                    entry["earliest"] = pa
                if entry["latest"] is None or pa > entry["latest"]:
                    entry["latest"] = pa

        for s in source_stats.values():
            if s["earliest"]:
                s["earliest"] = s["earliest"].isoformat()
            if s["latest"]:
                s["latest"] = s["latest"].isoformat()

        sources_list = sorted(source_stats.values(), key=lambda x: -x["article_count"])
        return Response({
            "event_id": event.id,
            "total_sources": len(sources_list),
            "sources": sources_list,
        })

    # ── Top entities ───────────────────────────────────────────────

    @action(detail=True, methods=["get"])
    def entities(self, request, pk=None):
        """Top entities mentioned in this event's articles."""
        event = self.get_object()
        article_ids = list(
            Article.objects.filter(
                story__event=event, is_duplicate=False,
            ).values_list("id", flat=True)[:500]
        )
        if not article_ids:
            return Response({"event_id": event.id, "entities": []})

        top_entities = (
            ArticleEntity.objects.filter(article_id__in=article_ids)
            .values(
                "entity_id",
                entity_name=F("entity__name"),
                entity_type=F("entity__entity_type"),
                entity_country=F("entity__country"),
            )
            .annotate(
                mention_count=Count("id"),
                avg_relevance=Avg("relevance_score"),
            )
            .order_by("-mention_count")[:30]
        )
        return Response({
            "event_id": event.id,
            "entities": list(top_entities),
        })

    # ── Related events ─────────────────────────────────────────────

    @action(detail=True, methods=["get"])
    def related(self, request, pk=None):
        """Related events by geographic proximity and shared entities."""
        event = self.get_object()
        related: list[dict] = []

        # Geographic proximity
        if event.location_lat and event.location_lon:
            lat, lon = float(event.location_lat), float(event.location_lon)
            geo_related = (
                Event.objects.filter(
                    location_lat__isnull=False,
                    location_lon__isnull=False,
                )
                .exclude(id=event.id)
                .extra(
                    select={
                        "distance": (
                            "ABS(location_lat - %s) + ABS(location_lon - %s)"
                        )
                    },
                    select_params=[lat, lon],
                )
                .order_by("distance")[:10]
            )
            for e in geo_related:
                related.append({
                    "event_id": e.id,
                    "title": e.title,
                    "event_type": e.event_type,
                    "location_name": e.location_name,
                    "country": e.location_country,
                    "importance": float(e.importance_score),
                    "relation": "geographic_proximity",
                    "distance": getattr(e, "distance", None),
                })

        # Entity overlap — events sharing the same entities
        article_ids = list(
            Article.objects.filter(
                story__event=event, is_duplicate=False,
            ).values_list("id", flat=True)[:300]
        )
        if article_ids:
            entity_ids = list(
                ArticleEntity.objects.filter(article_id__in=article_ids)
                .values_list("entity_id", flat=True)
                .distinct()[:50]
            )
            if entity_ids:
                shared_event_ids = (
                    Article.objects.filter(
                        article_entities__entity_id__in=entity_ids,
                        story__event__isnull=False,
                        is_duplicate=False,
                    )
                    .exclude(story__event=event)
                    .values_list("story__event_id", flat=True)
                    .distinct()[:20]
                )
                entity_events = Event.objects.filter(
                    id__in=list(shared_event_ids),
                ).order_by("-importance_score")[:10]
                for e in entity_events:
                    if not any(r["event_id"] == e.id for r in related):
                        related.append({
                            "event_id": e.id,
                            "title": e.title,
                            "event_type": e.event_type,
                            "location_name": e.location_name,
                            "country": e.location_country,
                            "importance": float(e.importance_score),
                            "relation": "shared_entities",
                        })

        return Response({
            "event_id": event.id,
            "related_count": len(related),
            "related": related,
        })

    # ── Articles ───────────────────────────────────────────────────

    @action(detail=True, methods=["get"])
    def articles(self, request, pk=None):
        """All non-duplicate articles for this event, across all stories."""
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

    # ── Stories ─────────────────────────────────────────────────────

    @action(detail=True, methods=["get"])
    def stories(self, request, pk=None):
        """Stories that compose this event."""
        event = self.get_object()
        qs = Story.objects.filter(event=event).order_by("-importance_score", "-last_published_at")
        serializer = StoryListSerializer(qs, many=True)
        return Response({
            "event_id": event.id,
            "event_title": event.title,
            "story_count": qs.count(),
            "stories": serializer.data,
        })

    # ── Explain ────────────────────────────────────────────────────

    @action(detail=True, methods=["get"])
    def explain(self, request, pk=None):
        """Explain how this event was inferred from its component stories.

        Returns the chain: articles → stories → event, showing how the
        intelligence engine clustered articles into stories and merged
        stories into this event.
        """
        event = self.get_object()
        metadata = event.metadata or {}

        # Story composition details
        stories = Story.objects.filter(event=event).order_by("-importance_score")
        story_chain = []
        for story in stories[:20]:
            articles = (
                Article.objects.filter(story=story, is_duplicate=False)
                .select_related("source")
                .order_by("-published_at")
                .values(
                    "id", "title", "source__name", "quality_score",
                    "importance_score", "published_at",
                )[:10]
            )
            article_data = []
            for a in articles:
                a["quality_score"] = float(a["quality_score"])
                a["importance_score"] = float(a["importance_score"])
                if a["published_at"]:
                    a["published_at"] = a["published_at"].isoformat()
                article_data.append(a)

            story_chain.append({
                "story_id": story.id,
                "title": story.title,
                "story_key": story.story_key,
                "article_count": story.article_count,
                "importance_score": float(story.importance_score),
                "articles": article_data,
            })

        # Source correlation from metadata
        source_correlation = metadata.get("source_correlation")

        # Narrative conflicts from metadata
        narrative_conflicts = metadata.get("narrative_conflicts", [])

        # Confidence breakdown
        confidence_factors = {
            "source_count": event.source_count,
            "story_count": event.story_count,
            "confidence_score": float(event.confidence_score),
            "geo_confidence": float(event.geo_confidence) if event.geo_confidence else None,
            "conflict_flag": event.conflict_flag,
            "narrative_conflicts": narrative_conflicts[:5] if narrative_conflicts else [],
        }

        return Response({
            "event_id": event.id,
            "event_title": event.title,
            "event_type": event.event_type,
            "description": event.description,
            "confidence_factors": confidence_factors,
            "source_correlation": source_correlation,
            "story_chain": story_chain,
            "timeline_json": event.timeline_json or [],
        })

    # ── Attach to case ─────────────────────────────────────────────

    @action(detail=True, methods=["post"], url_path="attach-case")
    def attach_case(self, request, pk=None):
        """Link this event to an investigation case."""
        event = self.get_object()
        case_id = request.data.get("case_id")
        notes = request.data.get("notes", "")

        if not case_id:
            return Response(
                {"error": "case_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from cases.models import Case, CaseEvent

        try:
            case = Case.objects.get(id=case_id)
        except Case.DoesNotExist:
            return Response(
                {"error": "Case not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        obj, created = CaseEvent.objects.get_or_create(
            case=case, event=event,
            defaults={
                "notes": notes,
                "added_by": request.user if request.user.is_authenticated else None,
            },
        )
        return Response(
            {
                "case_id": case.id,
                "event_id": event.id,
                "created": created,
                "case_event_id": obj.id,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    # ── Narratives / conflict analysis ─────────────────────────────

    @action(detail=True, methods=["get"])
    def narratives(self, request, pk=None):
        """Narrative/conflict analysis for this event."""
        event = self.get_object()
        stories = Story.objects.filter(event=event).order_by("-importance_score")
        narrative_groups = []
        for idx, story in enumerate(stories, 1):
            articles = (
                Article.objects.filter(story=story, is_duplicate=False)
                .select_related("source")
            )
            if not articles.exists():
                continue
            sources_list = []
            seen: set[int] = set()
            for a in articles:
                if a.source_id and a.source_id not in seen:
                    seen.add(a.source_id)
                    sources_list.append({
                        "name": a.source.name if a.source else "Unknown",
                        "trust_score": float(a.source.trust_score) if a.source else 0,
                        "country": a.source.country if a.source else "",
                    })
            narrative_groups.append({
                "narrative_id": story.id,
                "label": story.title or f"Narrative #{idx}",
                "stance": "primary" if idx == 1 else "alternative",
                "confidence": float(story.importance_score or 0),
                "article_count": articles.count(),
                "sources": sources_list,
                "summary": story.title or "",
                "key_claims": [],
            })

        has_conflict = len(narrative_groups) > 1
        return Response({
            "event_id": event.id,
            "has_conflict": has_conflict,
            "conflict_summary": (
                f"{len(narrative_groups)} narrative(s) detected"
                if has_conflict
                else "No conflicting narratives"
            ),
            "narratives": narrative_groups,
        })

    # ── Linked alerts ──────────────────────────────────────────────

    @action(detail=True, methods=["get"])
    def alerts(self, request, pk=None):
        """Alerts linked to this event (via metadata.event_id)."""
        from alerts.models import Alert

        event = self.get_object()
        alerts_qs = Alert.objects.filter(
            metadata__event_id=event.id,
        ).order_by("-triggered_at")[:20]
        results = [
            {
                "id": a.id,
                "title": a.title,
                "alert_type": a.alert_type,
                "severity": a.severity,
                "status": a.status,
                "triggered_at": a.triggered_at.isoformat() if a.triggered_at else None,
            }
            for a in alerts_qs
        ]
        return Response({"results": results})
