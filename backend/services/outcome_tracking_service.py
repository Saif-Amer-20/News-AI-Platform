"""Outcome Tracking Service — resolves prediction outcomes, computes accuracy."""
from __future__ import annotations

import logging
from decimal import Decimal

from django.db.models import Q, Avg
from django.utils import timezone

from sources.models import (
    AnalystFeedback,
    OutcomeRecord,
    PredictiveScore,
    AnomalyDetection,
    Event,
)

logger = logging.getLogger(__name__)


def resolve_outcome(
    *,
    target_type: str,
    target_id: int,
    actual_outcome: str,
    accuracy_status: str,
    resolution_notes: str = "",
) -> OutcomeRecord:
    """Resolve an outcome record with actual result."""
    outcome, created = OutcomeRecord.objects.get_or_create(
        target_type=target_type,
        target_id=target_id,
        defaults={"prediction_snapshot": _capture_prediction_snapshot(target_type, target_id)},
    )
    outcome.actual_outcome = actual_outcome
    outcome.accuracy_status = accuracy_status
    outcome.resolution_notes = resolution_notes
    outcome.resolved_at = timezone.now()
    outcome.outcome_snapshot = _capture_outcome_snapshot(target_type, target_id)
    outcome.save()

    logger.info(
        "Outcome resolved: %s#%d → %s", target_type, target_id, accuracy_status
    )
    return outcome


def auto_evaluate_predictions(hours: int = 72) -> int:
    """Auto-evaluate pending prediction outcomes based on feedback signals."""
    cutoff = timezone.now() - timezone.timedelta(hours=hours)
    pending = OutcomeRecord.objects.filter(
        accuracy_status="pending",
        created_at__lte=cutoff,
    )

    resolved_count = 0
    for outcome in pending:
        feedbacks = AnalystFeedback.objects.filter(
            target_type=outcome.target_type,
            target_id=outcome.target_id,
        )
        if not feedbacks.exists():
            continue

        fp_count = feedbacks.filter(feedback_type="false_positive").count()
        confirmed_count = feedbacks.filter(feedback_type="confirmed").count()
        useful_count = feedbacks.filter(feedback_type="useful").count()
        total = feedbacks.count()

        if total == 0:
            continue

        fp_ratio = fp_count / total
        positive_ratio = (confirmed_count + useful_count) / total

        if fp_ratio >= 0.6:
            accuracy = "inaccurate"
        elif positive_ratio >= 0.6:
            accuracy = "accurate"
        elif fp_ratio > 0 and positive_ratio > 0:
            accuracy = "partially_accurate"
        else:
            accuracy = "indeterminate"

        outcome.accuracy_status = accuracy
        outcome.resolved_at = timezone.now()
        outcome.actual_outcome = f"Auto-evaluated: {fp_count} FP, {confirmed_count} confirmed, {useful_count} useful out of {total}"
        outcome.outcome_snapshot = _capture_outcome_snapshot(
            outcome.target_type, outcome.target_id
        )
        outcome.save()
        resolved_count += 1

    logger.info("Auto-evaluated %d prediction outcomes", resolved_count)
    return resolved_count


def get_accuracy_stats(days: int = 30) -> dict:
    """Compute accuracy metrics for predictions."""
    since = timezone.now() - timezone.timedelta(days=days)
    resolved = OutcomeRecord.objects.filter(
        resolved_at__isnull=False, created_at__gte=since,
    )
    total = resolved.count()
    if total == 0:
        return {"period_days": days, "total_resolved": 0, "accuracy_rate": 0, "by_status": {}}

    by_status = {}
    for choice in OutcomeRecord.AccuracyStatus.choices:
        by_status[choice[0]] = resolved.filter(accuracy_status=choice[0]).count()

    accurate = by_status.get("accurate", 0) + by_status.get("partially_accurate", 0) * 0.5
    accuracy_rate = accurate / total if total else 0

    return {
        "period_days": days,
        "total_resolved": total,
        "accuracy_rate": round(accuracy_rate, 4),
        "by_status": by_status,
    }


def get_outcome_for_target(target_type: str, target_id: int) -> dict | None:
    """Get outcome record for a target."""
    try:
        o = OutcomeRecord.objects.get(target_type=target_type, target_id=target_id)
        return {
            "id": o.id,
            "target_type": o.target_type,
            "target_id": o.target_id,
            "expected_outcome": o.expected_outcome,
            "actual_outcome": o.actual_outcome,
            "accuracy_status": o.accuracy_status,
            "resolved_at": o.resolved_at.isoformat() if o.resolved_at else None,
            "resolution_notes": o.resolution_notes,
            "prediction_snapshot": o.prediction_snapshot,
            "outcome_snapshot": o.outcome_snapshot,
            "created_at": o.created_at.isoformat(),
        }
    except OutcomeRecord.DoesNotExist:
        return None


def _capture_prediction_snapshot(target_type: str, target_id: int) -> dict:
    """Snapshot prediction state at creation time."""
    snapshot = {"captured_at": timezone.now().isoformat()}
    try:
        if target_type == "prediction":
            ps = PredictiveScore.objects.get(pk=target_id)
            snapshot.update({
                "escalation_probability": str(ps.escalation_probability),
                "continuation_probability": str(ps.continuation_probability),
                "misleading_probability": str(ps.misleading_probability),
                "monitoring_priority": str(ps.monitoring_priority),
                "risk_trend": ps.risk_trend,
                "event_id": ps.event_id,
            })
        elif target_type == "anomaly":
            an = AnomalyDetection.objects.get(pk=target_id)
            snapshot.update({
                "anomaly_type": an.anomaly_type,
                "severity": an.severity,
                "deviation_factor": an.deviation_factor,
                "confidence": str(an.confidence),
            })
    except Exception:
        pass
    return snapshot


def _capture_outcome_snapshot(target_type: str, target_id: int) -> dict:
    """Capture current state at resolution time."""
    snapshot = {"captured_at": timezone.now().isoformat()}
    try:
        if target_type == "prediction":
            ps = PredictiveScore.objects.get(pk=target_id)
            ev = ps.event
            snapshot.update({
                "current_risk_trend": ps.risk_trend,
                "current_escalation": str(ps.escalation_probability),
                "event_importance": str(ev.importance_score),
                "event_source_count": ev.source_count,
                "event_conflict": ev.conflict_flag,
            })
        elif target_type == "anomaly":
            an = AnomalyDetection.objects.get(pk=target_id)
            snapshot.update({
                "current_status": an.status,
                "current_deviation": an.deviation_factor,
            })
    except Exception:
        pass
    return snapshot
