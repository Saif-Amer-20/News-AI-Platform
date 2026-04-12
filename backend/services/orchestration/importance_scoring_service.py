from __future__ import annotations

import logging
from decimal import Decimal

from django.db.models import Avg

from sources.models import Article, Story

logger = logging.getLogger(__name__)


class ImportanceScoringService:
    """
    Calculates importance_score for articles and stories.

    Article importance factors (weights sum to 1.0):
    - source_trust   (0.25): Source trust_score (0.00–1.00)
    - frequency      (0.25): How many articles exist in the same story cluster
    - topic_weight   (0.20): Number of matched topics / keyword rules
    - quality        (0.15): Article quality_score
    - recency        (0.15): Bonus for recently published articles

    Story importance = average importance of non-duplicate articles in the cluster.
    """

    WEIGHT_SOURCE_TRUST = Decimal("0.25")
    WEIGHT_FREQUENCY = Decimal("0.25")
    WEIGHT_TOPIC = Decimal("0.20")
    WEIGHT_QUALITY = Decimal("0.15")
    WEIGHT_RECENCY = Decimal("0.15")

    def score_article(self, article: Article) -> Article:
        source_trust = self._source_trust_factor(article)
        frequency = self._frequency_factor(article)
        topic_weight = self._topic_factor(article)
        quality = self._quality_factor(article)
        recency = self._recency_factor(article)

        importance = (
            self.WEIGHT_SOURCE_TRUST * source_trust
            + self.WEIGHT_FREQUENCY * frequency
            + self.WEIGHT_TOPIC * topic_weight
            + self.WEIGHT_QUALITY * quality
            + self.WEIGHT_RECENCY * recency
        )
        # Clamp to 0.00–1.00
        importance = max(Decimal("0.00"), min(Decimal("1.00"), importance))
        article.importance_score = importance.quantize(Decimal("0.01"))
        article.save(update_fields=["importance_score", "updated_at"])

        logger.debug(
            "Article %s importance=%.2f (trust=%.2f freq=%.2f topic=%.2f qual=%.2f rec=%.2f)",
            article.id,
            importance,
            source_trust,
            frequency,
            topic_weight,
            quality,
            recency,
        )
        return article

    def score_story(self, story: Story) -> Story:
        avg = (
            story.articles.filter(is_duplicate=False)
            .aggregate(avg_imp=Avg("importance_score"))
            .get("avg_imp")
        )
        story.importance_score = (
            Decimal(str(round(avg, 2))) if avg else Decimal("0.00")
        )
        story.save(update_fields=["importance_score", "updated_at"])
        return story

    # ── Factor calculations ──────────────────────────────────────

    def _source_trust_factor(self, article: Article) -> Decimal:
        """Source trust_score already in 0.00–1.00 range."""
        if not article.source_id:
            return Decimal("0.50")
        trust = article.source.trust_score
        return max(Decimal("0.00"), min(Decimal("1.00"), trust))

    def _frequency_factor(self, article: Article) -> Decimal:
        """More articles in the same story = higher importance.
        1 article → 0.10, 2 → 0.30, 3-5 → 0.60, 6-10 → 0.80, 10+ → 1.00
        """
        if not article.story_id:
            return Decimal("0.10")
        count = article.story.article_count
        if count <= 1:
            return Decimal("0.10")
        if count <= 2:
            return Decimal("0.30")
        if count <= 5:
            return Decimal("0.60")
        if count <= 10:
            return Decimal("0.80")
        return Decimal("1.00")

    def _topic_factor(self, article: Article) -> Decimal:
        """More matched topics/rules = more relevant.
        0 topics → 0.10, 1 → 0.40, 2 → 0.70, 3+ → 1.00
        """
        topic_count = article.matched_topics.count()
        rule_count = len(article.matched_rule_labels) if article.matched_rule_labels else 0
        combined = max(topic_count, rule_count)
        if combined == 0:
            return Decimal("0.10")
        if combined == 1:
            return Decimal("0.40")
        if combined == 2:
            return Decimal("0.70")
        return Decimal("1.00")

    def _quality_factor(self, article: Article) -> Decimal:
        """Direct quality_score pass-through."""
        return max(Decimal("0.00"), min(Decimal("1.00"), article.quality_score))

    def _recency_factor(self, article: Article) -> Decimal:
        """Recent articles get a boost. Within 1h → 1.0, 6h → 0.8, 24h → 0.5, older → 0.2."""
        from django.utils import timezone

        if not article.published_at:
            return Decimal("0.20")
        age = timezone.now() - article.published_at
        hours = age.total_seconds() / 3600
        if hours < 1:
            return Decimal("1.00")
        if hours < 6:
            return Decimal("0.80")
        if hours < 24:
            return Decimal("0.50")
        return Decimal("0.20")
