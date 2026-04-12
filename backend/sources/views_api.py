"""Public REST API viewsets for the Sources domain.

All viewsets are read-only by default.  Admin/write operations go through
the Django admin or the internal API.
"""
from __future__ import annotations

from django.db.models import Count, Q
from rest_framework import filters, status as http_status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Article, ArticleEntity, Entity, Event, Source, SourceFetchRun, Story
from .serializers import (
    ArticleAISummarySerializer,
    ArticleDetailSerializer,
    ArticleListSerializer,
    ArticleTranslationSerializer,
    EntitySerializer,
    EventDetailSerializer,
    EventListSerializer,
    SourceDetailSerializer,
    SourceFetchRunSerializer,
    SourceListSerializer,
    StoryDetailSerializer,
    StoryListSerializer,
)


class SourceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/v1/sources/         — list sources
    GET /api/v1/sources/{id}/    — source detail
    GET /api/v1/sources/{id}/fetch-runs/  — recent fetch runs
    """

    queryset = Source.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "description", "base_url"]
    ordering_fields = [
        "name",
        "trust_score",
        "total_articles_fetched",
        "last_checked_at",
    ]
    ordering = ["name"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return SourceDetailSerializer
        return SourceListSerializer

    @action(detail=True, methods=["get"], url_path="fetch-runs")
    def fetch_runs(self, request, pk=None):
        source = self.get_object()
        runs = SourceFetchRun.objects.filter(source=source).order_by("-started_at")[:50]
        serializer = SourceFetchRunSerializer(runs, many=True)
        return Response(serializer.data)


class ArticleViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/v1/articles/        — list articles (newest first)
    GET /api/v1/articles/{id}/   — article detail with entities
    """

    queryset = (
        Article.objects.select_related("source", "story")
        .filter(is_duplicate=False)
        .order_by("-published_at", "-created_at")
    )
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["title", "normalized_title", "content"]
    ordering_fields = [
        "published_at",
        "importance_score",
        "quality_score",
        "created_at",
    ]
    ordering = ["-published_at"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ArticleDetailSerializer
        return ArticleListSerializer

    def get_queryset(self):
        qs = super().get_queryset()

        # For detail actions, include duplicates so article pages always work
        if self.action in ("retrieve", "entities", "events", "related", "translate", "ai_summary"):
            qs = (
                Article.objects.select_related("source", "story")
                .order_by("-published_at", "-created_at")
            )

        # Optional filters via query params
        source_param = self.request.query_params.get("source")
        story_id = self.request.query_params.get("story")
        min_quality = self.request.query_params.get("min_quality")
        min_importance = self.request.query_params.get("min_importance")
        include_duplicates = self.request.query_params.get("include_duplicates")

        if source_param:
            try:
                qs = qs.filter(source_id=int(source_param))
            except (ValueError, TypeError):
                qs = qs.filter(source__name__icontains=source_param)
        if story_id:
            qs = qs.filter(story_id=story_id)
        if min_quality:
            qs = qs.filter(quality_score__gte=min_quality)
        if min_importance:
            qs = qs.filter(importance_score__gte=min_importance)
        if include_duplicates and include_duplicates.lower() in ("true", "1"):
            qs = Article.objects.select_related("source", "story").order_by(
                "-published_at", "-created_at"
            )
        return qs

    @action(detail=True, methods=["get"])
    def entities(self, request, pk=None):
        """GET /api/v1/articles/{id}/entities/ — entities extracted from this article."""
        article = self.get_object()
        links = (
            ArticleEntity.objects.filter(article=article)
            .select_related("entity")
            .order_by("-relevance_score")
        )
        data = [
            {
                "entity_id": ae.entity_id,
                "name": ae.entity.name,
                "entity_type": ae.entity.entity_type,
                "country": ae.entity.country,
                "relevance_score": ae.relevance_score,
                "mention_count": ae.mention_count,
                "context_snippet": ae.context_snippet,
            }
            for ae in links
        ]
        return Response({"entities": data})

    @action(detail=True, methods=["get"])
    def events(self, request, pk=None):
        """GET /api/v1/articles/{id}/events/ — events linked to this article via story."""
        article = self.get_object()
        events = []
        if article.story and article.story.event:
            ev = article.story.event
            events.append({
                "id": ev.id,
                "title": ev.title,
                "event_type": ev.event_type,
                "location_name": ev.location_name,
                "location_country": ev.location_country,
                "importance_score": ev.importance_score,
                "first_reported_at": ev.first_reported_at,
            })
        return Response({"events": events})

    @action(detail=True, methods=["get"])
    def related(self, request, pk=None):
        """GET /api/v1/articles/{id}/related/ — related articles."""
        article = self.get_object()
        related_qs = Article.objects.filter(is_duplicate=False).exclude(id=article.id)

        # Same story
        if article.story_id:
            same_story = related_qs.filter(story_id=article.story_id).select_related("source")[:5]
        else:
            same_story = Article.objects.none()

        # Shared entities
        entity_ids = ArticleEntity.objects.filter(article=article).values_list("entity_id", flat=True)
        shared_entity = (
            related_qs.filter(article_entities__entity_id__in=entity_ids)
            .exclude(id__in=same_story.values_list("id", flat=True))
            .select_related("source")
            .distinct()[:5]
        )

        def _serialize(a, relation):
            return {
                "id": a.id,
                "title": a.title,
                "source_name": a.source.name if a.source else "",
                "published_at": a.published_at,
                "importance_score": a.importance_score,
                "relation": relation,
            }

        data = [_serialize(a, "same_story") for a in same_story]
        data += [_serialize(a, "shared_entities") for a in shared_entity]
        return Response({"related": data})

    @action(detail=True, methods=["post"])
    def translate(self, request, pk=None):
        """POST /api/v1/articles/{id}/translate/ — translate article.

        Body: { "target_language": "ar" }
        Returns the ArticleTranslation object.
        """
        article = self.get_object()
        target_language = (request.data.get("target_language") or "ar").strip().lower()

        if len(target_language) > 10:
            return Response(
                {"error": "Invalid target_language."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        from services.translation_service import translate_article

        translation = translate_article(article, target_language)
        serializer = ArticleTranslationSerializer(translation)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="ai-summary")
    def ai_summary(self, request, pk=None):
        """POST /api/v1/articles/{id}/ai-summary/ — generate AI summary + predictions."""
        article = self.get_object()

        from services.ai_summary_service import generate_ai_summary

        summary_obj = generate_ai_summary(article)
        serializer = ArticleAISummarySerializer(summary_obj)
        return Response(serializer.data)


class StoryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/v1/stories/         — list stories
    GET /api/v1/stories/{id}/    — story detail with nested articles
    """

    queryset = Story.objects.select_related("event").order_by(
        "-last_published_at", "-updated_at"
    )
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["title", "story_key"]
    ordering_fields = [
        "importance_score",
        "article_count",
        "last_published_at",
    ]
    ordering = ["-last_published_at"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return StoryDetailSerializer
        return StoryListSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        event_id = self.request.query_params.get("event")
        min_articles = self.request.query_params.get("min_articles")
        if event_id:
            qs = qs.filter(event_id=event_id)
        if min_articles:
            qs = qs.filter(article_count__gte=min_articles)
        return qs


class EventViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/v1/events/          — list events
    GET /api/v1/events/{id}/     — event detail with stories + timeline
    GET /api/v1/events/conflicts/ — events with conflict_flag=True
    """

    queryset = Event.objects.order_by("-last_reported_at", "-updated_at")
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["title", "description", "location_name"]
    ordering_fields = [
        "confidence_score",
        "importance_score",
        "story_count",
        "source_count",
        "last_reported_at",
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

        if event_type:
            qs = qs.filter(event_type=event_type)
        if country:
            qs = qs.filter(location_country=country)
        if conflict_only and conflict_only.lower() in ("true", "1"):
            qs = qs.filter(conflict_flag=True)
        if min_confidence:
            qs = qs.filter(confidence_score__gte=min_confidence)
        return qs

    @action(detail=False, methods=["get"])
    def conflicts(self, request):
        qs = Event.objects.filter(conflict_flag=True).order_by("-last_reported_at")[:100]
        serializer = EventListSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def narratives(self, request, pk=None):
        """GET /api/v1/events/{id}/narratives/ — narrative/conflict analysis."""
        event = self.get_object()
        stories = event.stories.all().select_related("event")
        narrative_groups = []
        for idx, story in enumerate(stories, 1):
            articles = story.articles.filter(is_duplicate=False).select_related("source")
            if not articles.exists():
                continue
            sources_list = []
            seen = set()
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
                "confidence": float(story.coherence_score or 0),
                "article_count": articles.count(),
                "sources": sources_list,
                "summary": story.summary or "",
                "key_claims": [],
            })
        has_conflict = len(narrative_groups) > 1
        return Response({
            "event_id": event.id,
            "has_conflict": has_conflict,
            "conflict_summary": f"{len(narrative_groups)} narrative(s) detected" if has_conflict else "No conflicting narratives",
            "narratives": narrative_groups,
        })

    @action(detail=True, methods=["get"])
    def alerts(self, request, pk=None):
        """GET /api/v1/events/{id}/alerts/ — alerts linked to this event."""
        from alerts.models import Alert
        event = self.get_object()
        # Find alerts that reference this event in metadata
        alerts_qs = Alert.objects.filter(
            metadata__event_id=event.id
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


class EntityViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET /api/v1/entities/        — list entities
    GET /api/v1/entities/{id}/   — entity detail
    """

    queryset = Entity.objects.annotate(
        article_count=Count("article_entities")
    ).order_by("-article_count")
    serializer_class = EntitySerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "normalized_name", "canonical_name"]
    ordering_fields = ["name", "entity_type", "article_count"]
    ordering = ["-article_count"]

    def get_queryset(self):
        qs = super().get_queryset()
        entity_type = self.request.query_params.get("entity_type")
        country = self.request.query_params.get("country")
        if entity_type:
            qs = qs.filter(entity_type=entity_type)
        if country:
            qs = qs.filter(country=country)
        return qs
