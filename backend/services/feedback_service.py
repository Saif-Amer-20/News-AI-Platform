"""Feedback Service — handles analyst feedback submission and aggregation."""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from django.db.models import Count, Q
from django.utils import timezone

from sources.models import (
    AnalystFeedback,
    OutcomeRecord,
    AnomalyDetection,
    PredictiveScore,
    Event,
)

logger = logging.getLogger(__name__)


def submit_feedback(
    *,
    target_type: str,
    target_id: int,
    feedback_type: str,
    comment: str = "",
    analyst=None,
    confidence: float = 1.0,
) -> AnalystFeedback:
    """Create a feedback record with a context snapshot for auditability."""
    snapshot = _build_context_snapshot(target_type, target_id)

    fb = AnalystFeedback.objects.create(
        target_type=target_type,
        target_id=target_id,
        feedback_type=feedback_type,
        comment=comment,
        analyst=analyst,
        confidence=Decimal(str(confidence)),
        context_snapshot=snapshot,
    )
    logger.info("Feedback %s created: %s on %s#%d", fb.id, feedback_type, target_type, target_id)

    # Auto-create OutcomeRecord if one doesn't exist for predictions/anomalies
    if target_type in ("prediction", "anomaly"):
        OutcomeRecord.objects.get_or_create(
            target_type=target_type,
            target_id=target_id,
            defaults={"prediction_snapshot": snapshot},
        )

    return fb


def get_feedback_for_target(target_type: str, target_id: int) -> list[dict]:
    """Return all feedback entries for a given target."""
    return list(
        AnalystFeedback.objects.filter(
            target_type=target_type, target_id=target_id,
        ).values(
            "id", "feedback_type", "comment", "confidence",
            "analyst__username", "context_snapshot", "created_at",
        )
    )


def get_feedback_summary(target_type: str, target_id: int) -> dict:
    """Aggregate feedback stats for a target."""
    qs = AnalystFeedback.objects.filter(
        target_type=target_type, target_id=target_id,
    )
    counts = dict(
        qs.values_list("feedback_type").annotate(c=Count("id")).values_list("feedback_type", "c")
    )
    return {
        "target_type": target_type,
        "target_id": target_id,
        "total": sum(counts.values()),
        "by_type": counts,
        "latest_at": qs.order_by("-created_at").values_list("created_at", flat=True).first(),
    }


def get_feedback_stats_global(days: int = 30) -> dict:
    """Platform-wide feedback statistics."""
    since = timezone.now() - timezone.timedelta(days=days)
    qs = AnalystFeedback.objects.filter(created_at__gte=since)

    by_target = dict(
        qs.values_list("target_type").annotate(c=Count("id")).values_list("target_type", "c")
    )
    by_type = dict(
        qs.values_list("feedback_type").annotate(c=Count("id")).values_list("feedback_type", "c")
    )
    total = qs.count()
    fp_rate = by_type.get("false_positive", 0) / total if total else 0

    return {
        "period_days": days,
        "total_feedback": total,
        "by_target_type": by_target,
        "by_feedback_type": by_type,
        "false_positive_rate": round(fp_rate, 4),
    }


def _build_context_snapshot(target_type: str, target_id: int) -> dict[str, Any]:
    """Capture current scores/metrics for audit trail."""
    snapshot: dict[str, Any] = {"captured_at": timezone.now().isoformat()}
    try:
        if target_type == "event":
            ev = Event.objects.get(pk=target_id)
            snapshot["importance_score"] = str(ev.importance_score)
            snapshot["confidence_score"] = str(ev.confidence_score)
            snapshot["conflict_flag"] = ev.conflict_flag
            snapshot["source_count"] = ev.source_count
            ps = getattr(ev, "predictive_score", None)
            if ps:
                snapshot["escalation_probability"] = str(ps.escalation_probability)
                snapshot["monitoring_priority"] = str(ps.monitoring_priority)
                snapshot["risk_trend"] = ps.risk_trend
        elif target_type == "prediction":
            ps = PredictiveScore.objects.get(pk=target_id)
            snapshot["escalation_probability"] = str(ps.escalation_probability)
            snapshot["monitoring_priority"] = str(ps.monitoring_priority)
            snapshot["risk_trend"] = ps.risk_trend
            snapshot["event_id"] = ps.event_id
        elif target_type == "anomaly":
            an = AnomalyDetection.objects.get(pk=target_id)
            snapshot["anomaly_type"] = an.anomaly_type
            snapshot["severity"] = an.severity
            snapshot["deviation_factor"] = an.deviation_factor
            snapshot["confidence"] = str(an.confidence)
    except Exception:
        pass
    return snapshot
