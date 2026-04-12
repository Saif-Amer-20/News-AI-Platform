from __future__ import annotations

import hashlib
import logging
from datetime import timedelta
from decimal import Decimal

from django.db.models import Avg, Count, Max, Min
from django.utils import timezone

from sources.models import Event, Story

from .event_confidence_service import EventConfidenceService
from .geo_confidence_service import GeoConfidenceService
from .geo_extraction_service import GeoExtractionService
from .multi_source_correlation_service import MultiSourceCorrelationService
from .narrative_conflict_service import NarrativeConflictService
from .narrative_detection_service import NarrativeDetectionService
from .semantic_similarity_service import SemanticSimilarityService
from .temporal_evolution_service import TemporalEvolutionService

logger = logging.getLogger(__name__)


class EventResolutionService:
    """
    Maps stories to real-world events.

    Logic:
    1. Detect event_type from the story's articles.
    2. Extract primary geo location.
    3. Search for an existing event with similar type + location + time window.
    4. If found → attach story; else → create new event.
    """

    event_window_days = 5
    title_similarity_threshold = 0.40
    max_event_candidates = 200

    def __init__(self):
        self.narrative = NarrativeDetectionService()
        self.geo = GeoExtractionService()
        self.similarity = SemanticSimilarityService()
        self.confidence = EventConfidenceService()
        self.temporal = TemporalEvolutionService()
        self.conflict = NarrativeConflictService()
        self.geo_confidence = GeoConfidenceService()
        self.multi_source = MultiSourceCorrelationService()

    def resolve_event(self, story: Story) -> Event:
        """Assign or create an Event for the given Story."""
        # If story already has an event, just refresh it
        if story.event_id:
            self._refresh_event(story.event)
            self._run_intelligence(story.event, story)
            return story.event

        # Determine event type from the story's primary article
        primary_article = (
            story.articles.filter(is_duplicate=False)
            .order_by("-importance_score", "-published_at")
            .first()
        )
        if not primary_article:
            primary_article = story.articles.order_by("-published_at").first()

        event_type = Event.EventType.UNKNOWN
        geo = {}
        if primary_article:
            event_type = self.narrative.detect(primary_article)
            geo = self.geo.extract_geo(primary_article)

        # Search for matching existing event
        existing_event = self._find_matching_event(story, event_type, geo)

        if existing_event:
            story.event = existing_event
            story.save(update_fields=["event", "updated_at"])
            self._refresh_event(existing_event)
            self._run_intelligence(existing_event, story)
            logger.info(
                "Story %s attached to existing event %s",
                story.id,
                existing_event.id,
            )
            return existing_event

        # Create new event
        event = Event.objects.create(
            title=story.title,
            event_type=event_type,
            location_name=geo.get("location_name", ""),
            location_country=geo.get("location_country", ""),
            location_lat=geo.get("location_lat"),
            location_lon=geo.get("location_lon"),
            first_reported_at=story.first_published_at,
            last_reported_at=story.last_published_at,
            story_count=1,
        )
        story.event = event
        story.save(update_fields=["event", "updated_at"])
        self._run_intelligence(event, story)
        logger.info(
            "Story %s created new event %s [%s]",
            story.id,
            event.id,
            event_type,
        )
        return event

    def _run_intelligence(self, event: Event, story: Story) -> None:
        """Execute all intelligence sub-services on the event."""
        try:
            # Temporal evolution — add timeline entry for the primary article
            primary = (
                story.articles.filter(is_duplicate=False)
                .order_by("-published_at")
                .first()
            )
            if primary:
                self.temporal.track(event, primary)

            # Multi-source correlation
            self.multi_source.correlate(event)

            # Confidence scoring (depends on source_count from correlation)
            self.confidence.score_event(event)

            # Geo confidence
            self.geo_confidence.score(event)

            # Narrative conflict detection
            self.conflict.detect(event)
        except Exception:
            logger.exception("Intelligence sub-services failed for event %s", event.id)

    def _find_matching_event(
        self,
        story: Story,
        event_type: str,
        geo: dict,
    ) -> Event | None:
        window_start = timezone.now() - timedelta(days=self.event_window_days)

        candidates = Event.objects.filter(
            last_reported_at__gte=window_start,
        ).order_by("-last_reported_at")[: self.max_event_candidates]

        story_title = story.title.lower()
        best_event = None
        best_score = 0.0

        for event in candidates:
            score = 0.0

            # Title / text similarity
            text_sim = self.similarity.compute_similarity(
                story_title, event.title.lower()
            )
            score += text_sim * 0.4

            # Event type match bonus
            if event_type != "unknown" and event.event_type == event_type:
                score += 0.3

            # Location match bonus
            loc_name = geo.get("location_name", "")
            if loc_name and event.location_name:
                if loc_name.lower() == event.location_name.lower():
                    score += 0.3
                elif loc_name.lower() in event.location_name.lower():
                    score += 0.15

            if score > best_score and score >= 0.45:
                best_score = score
                best_event = event

        return best_event

    def _refresh_event(self, event: Event) -> None:
        stats = event.stories.aggregate(
            first_reported=Min("first_published_at"),
            last_reported=Max("last_published_at"),
            story_count=Count("id"),
        )
        avg_importance = (
            event.stories.aggregate(avg=Avg("importance_score")).get("avg")
        )
        event.first_reported_at = stats["first_reported"]
        event.last_reported_at = stats["last_reported"]
        event.story_count = stats["story_count"] or 0
        event.importance_score = (
            Decimal(str(round(avg_importance, 2)))
            if avg_importance
            else Decimal("0.00")
        )
        event.save(
            update_fields=[
                "first_reported_at",
                "last_reported_at",
                "story_count",
                "importance_score",
                "updated_at",
            ]
        )
