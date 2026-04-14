"""Source Reputation Learning — updates trust_score based on feedback/outcomes."""
from __future__ import annotations

import logging
from decimal import Decimal
from collections import defaultdict

from django.db.models import Count, Q, Avg
from django.utils import timezone

from sources.models import (
    Source,
    Article,
    Event,
    AnomalyDetection,
    AnalystFeedback,
    OutcomeRecord,
    SourceReputationLog,
)

logger = logging.getLogger(__name__)

# Safety: max change per cycle
MAX_TRUST_DELTA = Decimal("0.05")
MIN_TRUST = Decimal("0.10")
MAX_TRUST = Decimal("0.95")


def update_source_reputations(days: int = 30) -> int:
    """Recalculate source trust based on feedback signals."""
    since = timezone.now() - timezone.timedelta(days=days)
    updated = 0

    sources = Source.objects.filter(is_active=True)
    for source in sources:
        delta = _compute_trust_delta(source, since)
        if abs(delta) < Decimal("0.001"):
            continue

        # Clamp delta
        delta = max(-MAX_TRUST_DELTA, min(MAX_TRUST_DELTA, delta))
        old_trust = source.trust_score
        new_trust = max(MIN_TRUST, min(MAX_TRUST, old_trust + delta))

        if new_trust == old_trust:
            continue

        # Determine dominant reason
        reason = _determine_reason(source, since)

        SourceReputationLog.objects.create(
            source=source,
            previous_trust=old_trust,
            new_trust=new_trust,
            change_delta=new_trust - old_trust,
            reason=reason,
            evidence=_build_evidence(source, since),
        )
        source.trust_score = new_trust
        source.save(update_fields=["trust_score", "updated_at"])
        updated += 1

        logger.info(
            "Source %s trust: %s → %s (Δ%s, reason=%s)",
            source.slug, old_trust, new_trust, new_trust - old_trust, reason,
        )

    logger.info("Source reputation update complete: %d sources updated", updated)
    return updated


def get_source_trust_trend(source_id: int, limit: int = 20) -> list[dict]:
    """Return recent trust change history for a source."""
    logs = SourceReputationLog.objects.filter(
        source_id=source_id,
    ).order_by("-created_at")[:limit]
    return [
        {
            "id": log.id,
            "previous_trust": str(log.previous_trust),
            "new_trust": str(log.new_trust),
            "change_delta": str(log.change_delta),
            "reason": log.reason,
            "evidence": log.evidence,
            "is_rollback": log.is_rollback,
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ]


def rollback_trust_change(log_id: int, user=None) -> Source:
    """Rollback a specific trust change."""
    log = SourceReputationLog.objects.select_related("source").get(pk=log_id)
    source = log.source

    old_trust = source.trust_score
    source.trust_score = log.previous_trust
    source.save(update_fields=["trust_score", "updated_at"])

    # Mark original as rolled back
    log.is_rollback = True
    log.rolled_back_at = timezone.now()
    log.rolled_back_by = user
    log.save()

    # Create audit entry for rollback
    SourceReputationLog.objects.create(
        source=source,
        previous_trust=old_trust,
        new_trust=log.previous_trust,
        change_delta=log.previous_trust - old_trust,
        reason=SourceReputationLog.ChangeReason.MANUAL_OVERRIDE,
        evidence={"rollback_of": log.id, "original_reason": log.reason},
        is_rollback=True,
    )

    logger.info("Rolled back trust for source %s: %s → %s", source.slug, old_trust, log.previous_trust)
    return source


def _compute_trust_delta(source: Source, since) -> Decimal:
    """Compute trust delta from feedback and outcome signals."""
    # Get articles from this source in the period
    article_ids = list(
        Article.objects.filter(source=source, created_at__gte=since)
        .values_list("id", flat=True)
    )
    if not article_ids:
        return Decimal("0")

    # Get events linked to those articles (via stories)
    event_ids = list(
        Event.objects.filter(
            stories__articles__id__in=article_ids,
        ).values_list("id", flat=True).distinct()
    )

    # Aggregate feedback for events from this source
    fb_qs = AnalystFeedback.objects.filter(
        target_type="event",
        target_id__in=event_ids,
        created_at__gte=since,
    )
    fp_count = fb_qs.filter(feedback_type="false_positive").count()
    confirmed_count = fb_qs.filter(feedback_type="confirmed").count()
    useful_count = fb_qs.filter(feedback_type="useful").count()
    misleading_count = fb_qs.filter(feedback_type="misleading").count()
    total_fb = fb_qs.count()

    if total_fb == 0:
        return Decimal("0")

    # Positive signals push trust up
    positive_ratio = (confirmed_count + useful_count) / total_fb
    # Negative signals push trust down
    negative_ratio = (fp_count + misleading_count) / total_fb

    # Outcome accuracy for predictions on these events
    outcomes = OutcomeRecord.objects.filter(
        target_type="prediction",
        target_id__in=list(
            Event.objects.filter(id__in=event_ids)
            .filter(predictive_score__isnull=False)
            .values_list("predictive_score__id", flat=True)
        ),
        resolved_at__isnull=False,
    )
    accurate_count = outcomes.filter(
        accuracy_status__in=["accurate", "partially_accurate"]
    ).count()
    inaccurate_count = outcomes.filter(accuracy_status="inaccurate").count()
    total_outcomes = outcomes.count()

    outcome_bonus = Decimal("0")
    if total_outcomes > 0:
        accuracy_rate = accurate_count / total_outcomes
        outcome_bonus = Decimal(str(accuracy_rate * 0.02 - (1 - accuracy_rate) * 0.02))

    # Base delta from feedback
    delta = Decimal(str(positive_ratio * 0.03 - negative_ratio * 0.04))
    delta += outcome_bonus

    return delta


def _determine_reason(source: Source, since) -> str:
    """Determine the primary reason for trust change."""
    article_ids = list(
        Article.objects.filter(source=source, created_at__gte=since)
        .values_list("id", flat=True)
    )
    event_ids = list(
        Event.objects.filter(
            stories__articles__id__in=article_ids,
        ).values_list("id", flat=True).distinct()
    )
    fb_qs = AnalystFeedback.objects.filter(
        target_type="event",
        target_id__in=event_ids,
        created_at__gte=since,
    )
    fp = fb_qs.filter(feedback_type="false_positive").count()
    useful = fb_qs.filter(feedback_type__in=["confirmed", "useful"]).count()

    if fp > useful:
        return SourceReputationLog.ChangeReason.FALSE_POSITIVE
    elif useful > fp:
        return SourceReputationLog.ChangeReason.USEFUL_SIGNAL
    else:
        return SourceReputationLog.ChangeReason.PERIODIC_RECALC


def _build_evidence(source: Source, since) -> dict:
    """Build evidence dict for the trust change."""
    article_count = Article.objects.filter(
        source=source, created_at__gte=since,
    ).count()
    event_ids = list(
        Event.objects.filter(
            stories__articles__source=source,
            stories__articles__created_at__gte=since,
        ).values_list("id", flat=True).distinct()
    )
    fb_qs = AnalystFeedback.objects.filter(
        target_type="event",
        target_id__in=event_ids,
        created_at__gte=since,
    )
    fb_counts = dict(
        fb_qs.values_list("feedback_type")
        .annotate(c=Count("id"))
        .values_list("feedback_type", "c")
    )
    return {
        "period_since": since.isoformat(),
        "articles_produced": article_count,
        "events_linked": len(event_ids),
        "feedback_counts": fb_counts,
    }
