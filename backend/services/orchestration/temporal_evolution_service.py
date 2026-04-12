"""Temporal Evolution Service — track how an event develops over time.

Responsibilities
─────────────────
1. Append timeline entries to Event.timeline_json whenever a new article
   adds meaningful information.
2. Detect significant description changes between successive articles.
3. Maintain first_reported_at / last_reported_at on the event.
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

from django.utils import timezone

from sources.models import Article, Event

from .semantic_similarity_service import SemanticSimilarityService

logger = logging.getLogger(__name__)


class TemporalEvolutionService:
    """Build and maintain an event's chronological timeline."""

    # If a new article's content similarity to the last timeline entry is
    # below this threshold, it counts as a "description change".
    CHANGE_THRESHOLD = 0.55

    # Maximum number of timeline entries to keep per event.
    MAX_TIMELINE_ENTRIES = 200

    def __init__(self):
        self.similarity = SemanticSimilarityService()

    def track(self, event: Event, article: Article) -> dict | None:
        """
        Append a timeline entry if the article adds new information.
        Returns the new timeline entry dict, or None if skipped.
        """
        if not article.published_at:
            ts = timezone.now().isoformat()
        else:
            ts = article.published_at.isoformat()

        # Build summary from the first ~200 chars of the article's content
        summary = (article.content or article.title)[:200].strip()
        if not summary:
            return None

        source_id = article.source_id
        source_name = article.source.name if article.source else ""

        timeline: list[dict] = list(event.timeline_json or [])

        # Check for redundancy against the most recent entry
        if timeline:
            last_summary = timeline[-1].get("summary", "")
            sim = self.similarity.compute_similarity(summary, last_summary)
            if sim > 0.80:
                # Too similar — skip to avoid bloat
                return None

        entry = {
            "ts": ts,
            "summary": summary,
            "source_id": source_id,
            "source_name": source_name,
            "article_id": article.id,
            "is_change": self._is_description_change(timeline, summary),
        }

        timeline.append(entry)

        # Trim if over limit
        if len(timeline) > self.MAX_TIMELINE_ENTRIES:
            timeline = timeline[-self.MAX_TIMELINE_ENTRIES:]

        event.timeline_json = timeline

        # Update temporal bounds
        pub = article.published_at or timezone.now()
        if event.first_reported_at is None or pub < event.first_reported_at:
            event.first_reported_at = pub
        if event.last_reported_at is None or pub > event.last_reported_at:
            event.last_reported_at = pub

        event.save(
            update_fields=[
                "timeline_json",
                "first_reported_at",
                "last_reported_at",
                "updated_at",
            ]
        )

        logger.debug(
            "Event %s timeline entry added (total=%d, change=%s)",
            event.id,
            len(timeline),
            entry["is_change"],
        )
        return entry

    def _is_description_change(self, timeline: list[dict], new_summary: str) -> bool:
        """Return True if *new_summary* is substantially different from recent entries."""
        if not timeline:
            return False
        # Compare against last 3 entries
        recent_summaries = [e["summary"] for e in timeline[-3:]]
        avg_sim = 0.0
        for s in recent_summaries:
            avg_sim += self.similarity.compute_similarity(new_summary, s)
        avg_sim /= len(recent_summaries)
        return avg_sim < self.CHANGE_THRESHOLD
