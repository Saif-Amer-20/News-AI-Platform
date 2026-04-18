"""Entity Intelligence Service — v2 (quality-tuned).

Computes influence scores, detects growth anomalies, and emits signals
for all canonical entities in the system.

Runs periodically via Celery Beat and writes to:
  - EntityInfluenceScore   (one row per entity, upserted)
  - EntitySignal           (new rows for detected anomalies)

Influence Score Formula (v2)
────────────────────────────
  graph_score    = 0.40 × degree_centrality (only from co_occ ≥ 2 relationships)
  velocity_score = 0.35 × normalised 7-day mention velocity
  diversity_score = 0.25 × source diversity (distinct sources / total sources)

  influence_score = graph_score + velocity_score + diversity_score

Signals Generated (v2 — with minimum thresholds)
────────────────────────────────────────────────
  MENTION_SPIKE   — 24h mentions ≥ 5 AND ≥ 2× 7-day daily average
  RAPID_GROWTH    — prior7d ≥ 5 AND 7d mentions ≥ 1.5× prior7d
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from sources.models import (
    Article,
    ArticleEntity,
    Entity,
    EntityInfluenceScore,
    EntityRelationship,
    EntitySignal,
    Source,
)

logger = logging.getLogger(__name__)

# Minimum article count to be included in influence scoring
_MIN_ARTICLES = 2
# Max entities to score per run
_MAX_ENTITIES = 2000
# Spike: 24h_mentions / (7d_mentions / 7) must exceed this
_SPIKE_RATIO = 2.0
# Spike: ABSOLUTE minimum 24h mentions to trigger
_SPIKE_MIN_24H = 5
# Rapid growth: 7d_mentions vs prior 7d
_GROWTH_RATIO = 1.5
# Growth: ABSOLUTE minimum prior-7d mentions to trigger
_GROWTH_MIN_PRIOR7D = 5
# Minimum co-occurrence for graph degree calculations
_MIN_CO_OCC_FOR_DEGREE = 2


class EntityIntelligenceService:
    """Computes and caches entity influence scores and anomaly signals."""

    def run_scoring(self, *, max_entities: int = _MAX_ENTITIES) -> dict:
        """Main entry point — score all entities and emit signals.

        Returns a stats dict.
        """
        stats = {
            "scored": 0,
            "skipped_blocked": 0,
            "signals_mention_spike": 0,
            "signals_rapid_growth": 0,
        }

        now = timezone.now()
        cutoff_24h = now - timedelta(hours=24)
        cutoff_7d  = now - timedelta(days=7)
        cutoff_30d = now - timedelta(days=30)
        cutoff_prior_7d_start = now - timedelta(days=14)

        # P1: Get blocked entity IDs from relationship service
        from services.orchestration.entity_relationship_service import EntityRelationshipService
        blocked_ids = EntityRelationshipService()._build_blocked_entity_ids()

        # All canonical entities with enough mentions, excluding blocked
        entities = list(
            Entity.objects
            .exclude(id__in=blocked_ids)
            .annotate(total_articles=Count("article_entities"))
            .filter(total_articles__gte=_MIN_ARTICLES)
            .order_by("-total_articles")[:max_entities]
        )

        if not entities:
            return stats

        entity_ids = [e.id for e in entities]
        stats["skipped_blocked"] = len(blocked_ids)

        # ── Mention windows ──────────────────────────────────────────────
        # Batch-compute 24h / 7d / 30d counts per entity
        window_data: dict[int, dict] = {eid: {"m24h": 0, "m7d": 0, "m30d": 0, "prior7d": 0} for eid in entity_ids}

        for row in (
            ArticleEntity.objects
            .filter(
                entity_id__in=entity_ids,
                article__published_at__gte=cutoff_30d,
                article__is_duplicate=False,
            )
            .values("entity_id", "article__published_at")
        ):
            eid = row["entity_id"]
            pub = row["article__published_at"]
            if pub is None:
                continue
            d = window_data[eid]
            if pub >= cutoff_24h:
                d["m24h"] += 1
            if pub >= cutoff_7d:
                d["m7d"] += 1
            d["m30d"] += 1

        # Prior 7d window (for growth rate)
        for row in (
            ArticleEntity.objects
            .filter(
                entity_id__in=entity_ids,
                article__published_at__gte=cutoff_prior_7d_start,
                article__published_at__lt=cutoff_7d,
                article__is_duplicate=False,
            )
            .values("entity_id")
            .annotate(n=Count("id"))
        ):
            eid = row["entity_id"]
            if eid in window_data:
                window_data[eid]["prior7d"] = row["n"]

        # ── Source diversity ─────────────────────────────────────────────
        total_sources = max(Source.objects.filter(is_active=True).count(), 1)

        diversity_data: dict[int, int] = {}
        for row in (
            ArticleEntity.objects
            .filter(
                entity_id__in=entity_ids,
                article__is_duplicate=False,
            )
            .values("entity_id")
            .annotate(distinct_sources=Count("article__source", distinct=True))
        ):
            diversity_data[row["entity_id"]] = row["distinct_sources"]

        # ── Graph degree (P0: only from meaningful relationships) ────────
        degree_data: dict[int, float] = {}  # entity_id → sum(strength_scores)

        for rel in EntityRelationship.objects.filter(
            (Q(entity_a_id__in=entity_ids) | Q(entity_b_id__in=entity_ids)),
            co_occurrence_count__gte=_MIN_CO_OCC_FOR_DEGREE,
        ).values("entity_a_id", "entity_b_id", "strength_score"):
            s = float(rel["strength_score"])
            degree_data[rel["entity_a_id"]] = degree_data.get(rel["entity_a_id"], 0) + s
            degree_data[rel["entity_b_id"]] = degree_data.get(rel["entity_b_id"], 0) + s

        # Normalise degree (max weighted degree across all entities)
        max_degree = max(degree_data.values(), default=1.0)

        # ── Compute and save scores ──────────────────────────────────────
        all_7d_counts = [window_data[eid]["m7d"] for eid in entity_ids]
        max_7d = max(all_7d_counts, default=1) or 1

        all_diversity = [diversity_data.get(eid, 0) for eid in entity_ids]
        # P1: Normalize diversity against actual source count, not max entity diversity
        # This gives meaningful values (e.g., 5/8 = 0.625 instead of 5/7 ≈ 0.71)

        for entity in entities:
            eid = entity.id
            wd = window_data[eid]

            m24h    = wd["m24h"]
            m7d     = wd["m7d"]
            m30d    = wd["m30d"]
            prior7d = wd["prior7d"]

            # Normalised sub-scores
            n_degree    = degree_data.get(eid, 0) / max_degree
            n_velocity  = m7d / max_7d
            n_diversity = diversity_data.get(eid, 0) / total_sources

            influence = (
                0.40 * n_degree
                + 0.35 * n_velocity
                + 0.25 * n_diversity
            )

            daily_avg_7d = m7d / 7
            # P1: growth_flag requires BOTH absolute minimum AND ratio
            growth_flag = (
                m24h >= _SPIKE_MIN_24H
                and m24h >= _SPIKE_RATIO * max(daily_avg_7d, 1)
            )

            try:
                with transaction.atomic():
                    inf, _ = EntityInfluenceScore.objects.update_or_create(
                        entity_id=eid,
                        defaults={
                            "degree_centrality":      Decimal(str(round(n_degree, 5))),
                            "weighted_degree":        Decimal(str(round(degree_data.get(eid, 0), 5))),
                            "mentions_last_24h":      m24h,
                            "mentions_last_7d":       m7d,
                            "mentions_last_30d":      m30d,
                            "velocity_score":         Decimal(str(round(n_velocity, 4))),
                            "growth_flag":            growth_flag,
                            "influence_score":        Decimal(str(round(influence, 5))),
                        },
                    )
                stats["scored"] += 1
            except Exception:
                logger.debug("Failed to score entity %s", eid, exc_info=True)
                continue

            # ── Signals (P1: strict thresholds) ─────────────────────────
            # MENTION_SPIKE: absolute minimum + ratio
            if growth_flag:
                self._maybe_emit(
                    entity_id=eid,
                    signal_type=EntitySignal.SignalType.MENTION_SPIKE,
                    severity=EntitySignal.Severity.HIGH if m24h > 5 * max(daily_avg_7d, 1) else EntitySignal.Severity.MEDIUM,
                    title=f"Mention spike: {entity.canonical_name or entity.name}",
                    description=(
                        f"24h mentions: {m24h} (daily 7d avg: {daily_avg_7d:.1f}). "
                        f"Ratio: {m24h / max(daily_avg_7d, 0.1):.1f}×."
                    ),
                    metadata={"m24h": m24h, "m7d": m7d, "daily_avg": daily_avg_7d},
                )
                stats["signals_mention_spike"] += 1

            # RAPID_GROWTH: absolute minimum prior7d + ratio
            if prior7d >= _GROWTH_MIN_PRIOR7D and m7d >= _GROWTH_RATIO * prior7d:
                self._maybe_emit(
                    entity_id=eid,
                    signal_type=EntitySignal.SignalType.RAPID_GROWTH,
                    severity=EntitySignal.Severity.MEDIUM,
                    title=f"Rapid growth: {entity.canonical_name or entity.name}",
                    description=(
                        f"7d mentions: {m7d} vs prior 7d: {prior7d} "
                        f"({(m7d/prior7d - 1)*100:.0f}% growth)."
                    ),
                    metadata={"m7d": m7d, "prior7d": prior7d},
                )
                stats["signals_rapid_growth"] += 1

        # ── Update influence_rank (rank by score descending) ─────────────
        ranked = list(
            EntityInfluenceScore.objects
            .order_by("-influence_score")
            .values_list("id", flat=True)
        )
        for rank, pk in enumerate(ranked, start=1):
            EntityInfluenceScore.objects.filter(pk=pk).update(influence_rank=rank)

        logger.info(
            "EntityIntelligenceService.run_scoring: scored=%d spike_signals=%d growth_signals=%d",
            stats["scored"],
            stats["signals_mention_spike"],
            stats["signals_rapid_growth"],
        )
        return stats

    def get_most_connected(self, *, entity_type: str | None = None, limit: int = 20) -> list[dict]:
        """Return entities ranked by weighted graph degree (most connected first)."""
        from services.orchestration.entity_relationship_service import EntityRelationshipService
        blocked_ids = EntityRelationshipService()._build_blocked_entity_ids()

        qs = (
            EntityInfluenceScore.objects
            .select_related("entity")
            .exclude(entity_id__in=blocked_ids)
            .order_by("-weighted_degree")
        )
        if entity_type:
            qs = qs.filter(entity__entity_type=entity_type)
        results = []
        for inf in qs[:limit]:
            results.append({
                "id":            inf.entity_id,
                "name":          inf.entity.canonical_name or inf.entity.name,
                "type":          inf.entity.entity_type,
                "weighted_degree": float(inf.weighted_degree),
                "influence_score": float(inf.influence_score),
                "mentions_7d":   inf.mentions_last_7d,
                "rank":          inf.influence_rank,
            })
        return results

    def get_fastest_growing(self, *, entity_type: str | None = None, limit: int = 20) -> list[dict]:
        """Return entities with the largest 24h mention spike."""
        from services.orchestration.entity_relationship_service import EntityRelationshipService
        blocked_ids = EntityRelationshipService()._build_blocked_entity_ids()

        qs = (
            EntityInfluenceScore.objects
            .select_related("entity")
            .filter(growth_flag=True)
            .exclude(entity_id__in=blocked_ids)
            .order_by("-velocity_score")
        )
        if entity_type:
            qs = qs.filter(entity__entity_type=entity_type)
        results = []
        for inf in qs[:limit]:
            results.append({
                "id":           inf.entity_id,
                "name":         inf.entity.canonical_name or inf.entity.name,
                "type":         inf.entity.entity_type,
                "mentions_24h": inf.mentions_last_24h,
                "mentions_7d":  inf.mentions_last_7d,
                "velocity":     float(inf.velocity_score),
                "growth_flag":  inf.growth_flag,
            })
        return results

    # ── Private helpers ───────────────────────────────────────────────────

    def _maybe_emit(
        self,
        *,
        entity_id: int,
        signal_type: str,
        severity: str,
        title: str,
        description: str,
        metadata: dict,
        related_entity_id: int | None = None,
    ) -> None:
        """Create a signal unless a recent identical one already exists."""
        recent_cutoff = timezone.now() - timedelta(hours=12)
        already = EntitySignal.objects.filter(
            entity_id=entity_id,
            signal_type=signal_type,
            created_at__gte=recent_cutoff,
        ).exists()
        if not already:
            EntitySignal.objects.create(
                entity_id=entity_id,
                signal_type=signal_type,
                severity=severity,
                title=title,
                description=description,
                metadata=metadata,
                related_entity_id=related_entity_id,
                expires_at=timezone.now() + timedelta(days=3),
            )
