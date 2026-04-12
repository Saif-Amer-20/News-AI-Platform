"""Geo Confidence Service — score how reliable an event's location is.

Factors
───────
1. Location mention count — how often the location appears across articles.
2. Source agreement — how many independent sources mention the same location.
3. Specificity — coordinates vs. country-level vs. unknown.
4. Entity-backed — whether a matching Location entity exists.

Output: Event.geo_confidence (0.00 – 1.00)
"""
from __future__ import annotations

import logging
from collections import Counter
from decimal import Decimal

from sources.models import Article, ArticleEntity, Entity, Event

logger = logging.getLogger(__name__)


class GeoConfidenceService:
    """Calculate and persist geo_confidence on an Event."""

    def score(self, event: Event) -> Decimal:
        """Compute and persist ``geo_confidence``.  Returns the score."""
        if not event.location_name:
            event.geo_confidence = Decimal("0.00")
            event.save(update_fields=["geo_confidence", "updated_at"])
            return event.geo_confidence

        articles = list(
            Article.objects.filter(
                story__event=event,
                is_duplicate=False,
            ).select_related("source")[:200]
        )

        if not articles:
            event.geo_confidence = Decimal("0.10")
            event.save(update_fields=["geo_confidence", "updated_at"])
            return event.geo_confidence

        mention_score = self._mention_score(articles, event.location_name)
        source_agreement = self._source_agreement_score(articles, event.location_name)
        specificity = self._specificity_score(event)
        entity_backed = self._entity_backed_score(event)

        raw = (
            0.30 * mention_score
            + 0.30 * source_agreement
            + 0.20 * specificity
            + 0.20 * entity_backed
        )
        confidence = Decimal(str(round(min(raw, 1.0), 2)))
        event.geo_confidence = confidence
        event.save(update_fields=["geo_confidence", "updated_at"])

        logger.debug(
            "Event %s geo_confidence=%.2f (mention=%.2f agree=%.2f spec=%.2f entity=%.2f)",
            event.id,
            confidence,
            mention_score,
            source_agreement,
            specificity,
            entity_backed,
        )
        return confidence

    # ── Sub-scores ────────────────────────────────────────────────

    def _mention_score(self, articles: list[Article], location: str) -> float:
        """How often the event location name appears in articles' text."""
        location_lower = location.lower()
        total_mentions = 0
        for a in articles:
            text = f"{a.title} {a.content}".lower()
            total_mentions += text.count(location_lower)
        # Logarithmic scaling: 1→0.3, 5→0.7, 10+→1.0
        if total_mentions == 0:
            return 0.0
        if total_mentions <= 2:
            return 0.30
        if total_mentions <= 5:
            return 0.60
        if total_mentions <= 10:
            return 0.80
        return 1.0

    def _source_agreement_score(self, articles: list[Article], location: str) -> float:
        """How many distinct sources mention the event location."""
        location_lower = location.lower()
        agreeing_sources: set[int] = set()
        for a in articles:
            text = f"{a.title} {a.content}".lower()
            if location_lower in text:
                agreeing_sources.add(a.source_id)
        count = len(agreeing_sources)
        if count == 0:
            return 0.0
        if count == 1:
            return 0.30
        if count == 2:
            return 0.60
        if count <= 4:
            return 0.85
        return 1.0

    def _specificity_score(self, event: Event) -> float:
        """Score based on how specific the location data is."""
        score = 0.0
        if event.location_name:
            score += 0.30
        if event.location_country:
            score += 0.20
        if event.location_lat is not None and event.location_lon is not None:
            score += 0.50
        return score

    def _entity_backed_score(self, event: Event) -> float:
        """Check if there's a matching Location entity in the database."""
        if not event.location_name:
            return 0.0
        exists = Entity.objects.filter(
            entity_type=Entity.EntityType.LOCATION,
            normalized_name__icontains=event.location_name.lower()[:50],
        ).exists()
        return 1.0 if exists else 0.0
