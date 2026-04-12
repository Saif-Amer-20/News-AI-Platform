from __future__ import annotations

import logging
from decimal import Decimal

from django.db.models import Avg, Count, Q

from sources.models import Article, Source

logger = logging.getLogger(__name__)


class SourceReliabilityService:
    """Dynamically updates Source.trust_score based on content quality and duplicate trends."""

    # Weight distribution for trust recalculation
    WEIGHT_QUALITY = Decimal("0.40")
    WEIGHT_DUP_RATIO = Decimal("0.30")
    WEIGHT_HEALTH = Decimal("0.30")

    # Minimum articles before dynamic scoring kicks in
    MIN_ARTICLES_FOR_SCORING = 10

    def update_source_stats(self, source: Source) -> Source:
        """Recalculate reliability counters and trust_score for a single source."""
        total = Article.objects.filter(source=source).count()
        duplicates = Article.objects.filter(source=source, is_duplicate=True).count()
        low_quality = Article.objects.filter(
            source=source, quality_score__lt=Decimal("0.30")
        ).count()
        avg_quality = (
            Article.objects.filter(source=source)
            .aggregate(avg_q=Avg("quality_score"))
            .get("avg_q")
        )

        source.total_articles_fetched = total
        source.total_duplicates = duplicates
        source.total_low_quality = low_quality
        source.avg_quality_score = (
            Decimal(str(round(avg_quality, 2)))
            if avg_quality
            else Decimal("0.50")
        )

        if total >= self.MIN_ARTICLES_FOR_SCORING:
            source.trust_score = self._calculate_trust(source)

        source.save(
            update_fields=[
                "total_articles_fetched",
                "total_duplicates",
                "total_low_quality",
                "avg_quality_score",
                "trust_score",
                "updated_at",
            ]
        )
        logger.info(
            "Source %s reliability updated: trust=%.2f total=%d dups=%d low_q=%d avg_q=%.2f",
            source.name,
            source.trust_score,
            total,
            duplicates,
            low_quality,
            source.avg_quality_score,
        )
        return source

    def _calculate_trust(self, source: Source) -> Decimal:
        total = source.total_articles_fetched or 1

        # Quality factor: avg quality of articles from this source
        quality_factor = max(
            Decimal("0.00"),
            min(Decimal("1.00"), source.avg_quality_score),
        )

        # Duplicate ratio factor: lower dup ratio = higher trust
        dup_ratio = Decimal(str(source.total_duplicates)) / Decimal(str(total))
        dup_factor = max(Decimal("0.00"), Decimal("1.00") - dup_ratio)

        # Health factor: based on health_status
        health_map = {
            Source.HealthStatus.HEALTHY: Decimal("1.00"),
            Source.HealthStatus.DEGRADED: Decimal("0.60"),
            Source.HealthStatus.FAILING: Decimal("0.20"),
            Source.HealthStatus.UNKNOWN: Decimal("0.50"),
        }
        health_factor = health_map.get(
            source.health_status, Decimal("0.50")
        )

        trust = (
            self.WEIGHT_QUALITY * quality_factor
            + self.WEIGHT_DUP_RATIO * dup_factor
            + self.WEIGHT_HEALTH * health_factor
        )

        return max(Decimal("0.05"), min(Decimal("1.00"), trust)).quantize(
            Decimal("0.01")
        )

    def update_all_sources(self) -> int:
        """Batch recalculate trust for all active sources."""
        sources = Source.objects.filter(is_active=True)
        count = 0
        for source in sources:
            self.update_source_stats(source)
            count += 1
        logger.info("Updated reliability for %d sources.", count)
        return count
