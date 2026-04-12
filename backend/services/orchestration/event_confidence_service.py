"""Event Confidence Model — score how trustworthy an event is.

Factors
───────
1. Source count — more independent sources → higher confidence.
2. Source diversity — different media types / countries → higher confidence.
3. Source trust — average trust_score of contributing sources.
4. Article consistency — how similar the articles' titles are to each other.

Output: Event.confidence_score (0.00 – 1.00)
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.db.models import Avg, Count

from sources.models import Article, Event

from .semantic_similarity_service import SemanticSimilarityService

logger = logging.getLogger(__name__)


class EventConfidenceService:
    """Calculate and persist a composite confidence score for an Event."""

    # Weights for the four sub-scores (must sum to 1.0)
    W_SOURCE_COUNT = 0.25
    W_DIVERSITY = 0.25
    W_TRUST = 0.25
    W_CONSISTENCY = 0.25

    def __init__(self):
        self.similarity = SemanticSimilarityService()

    def score_event(self, event: Event) -> Decimal:
        """Compute and persist `confidence_score` on the event.  Returns the score."""
        articles = self._get_event_articles(event)

        if not articles:
            event.confidence_score = Decimal("0.00")
            event.save(update_fields=["confidence_score", "updated_at"])
            return event.confidence_score

        source_count_score = self._source_count_score(articles)
        diversity_score = self._diversity_score(articles)
        trust_score = self._trust_score(articles)
        consistency_score = self._consistency_score(articles)

        raw = (
            self.W_SOURCE_COUNT * source_count_score
            + self.W_DIVERSITY * diversity_score
            + self.W_TRUST * trust_score
            + self.W_CONSISTENCY * consistency_score
        )
        confidence = Decimal(str(round(min(raw, 1.0), 2)))

        # Persist
        update_fields = ["confidence_score", "source_count", "updated_at"]
        event.confidence_score = confidence
        event.source_count = self._distinct_source_count(articles)
        event.save(update_fields=update_fields)

        logger.info(
            "Event %s confidence=%.2f (src=%.2f div=%.2f trust=%.2f cons=%.2f)",
            event.id,
            confidence,
            source_count_score,
            diversity_score,
            trust_score,
            consistency_score,
        )
        return confidence

    # ── Sub-scores ────────────────────────────────────────────────

    def _source_count_score(self, articles: list[Article]) -> float:
        """More distinct sources → higher score (logarithmic curve, caps at 1.0)."""
        distinct = self._distinct_source_count(articles)
        if distinct <= 1:
            return 0.20
        if distinct == 2:
            return 0.50
        if distinct == 3:
            return 0.70
        if distinct <= 5:
            return 0.85
        return 1.0

    def _diversity_score(self, articles: list[Article]) -> float:
        """Score based on how many distinct source_types and countries appear."""
        source_types: set[str] = set()
        countries: set[str] = set()
        for a in articles:
            src = a.source
            source_types.add(src.source_type)
            if src.country:
                countries.add(src.country)

        type_diversity = min(len(source_types) / 3.0, 1.0)  # 3+ types = perfect
        country_diversity = min(len(countries) / 3.0, 1.0)  # 3+ countries = perfect
        return (type_diversity + country_diversity) / 2.0

    def _trust_score(self, articles: list[Article]) -> float:
        """Weighted average trust_score of contributing sources."""
        if not articles:
            return 0.50
        total_trust = sum(float(a.source.trust_score) for a in articles)
        return min(total_trust / len(articles), 1.0)

    def _consistency_score(self, articles: list[Article]) -> float:
        """
        Pairwise title similarity across articles.
        High consistency → they agree.  Low → possible conflicting reports.
        """
        titles = [a.normalized_title or a.title.lower() for a in articles]
        if len(titles) < 2:
            return 0.80  # single article — moderate confidence

        # Sample up to 20 pairs to avoid O(n^2) on large events
        pairs_checked = 0
        similarity_sum = 0.0
        max_pairs = 20
        for i in range(len(titles)):
            for j in range(i + 1, len(titles)):
                similarity_sum += self.similarity.compute_similarity(titles[i], titles[j])
                pairs_checked += 1
                if pairs_checked >= max_pairs:
                    break
            if pairs_checked >= max_pairs:
                break

        return similarity_sum / pairs_checked if pairs_checked else 0.50

    # ── Helpers ───────────────────────────────────────────────────

    def _get_event_articles(self, event: Event) -> list[Article]:
        """Return non-duplicate articles linked to this event's stories."""
        return list(
            Article.objects.filter(
                story__event=event,
                is_duplicate=False,
            ).select_related("source")[:200]
        )

    def _distinct_source_count(self, articles: list[Article]) -> int:
        source_ids = {a.source_id for a in articles}
        return len(source_ids)
