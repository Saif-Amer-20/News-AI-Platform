"""Learning Data Store — captures training/evaluation records for the learning loop."""
from __future__ import annotations

import logging
from decimal import Decimal

from django.db.models import Count, Q, Avg
from django.utils import timezone

from sources.models import (
    Event,
    AnomalyDetection,
    PredictiveScore,
    AnalystFeedback,
    OutcomeRecord,
    LearningRecord,
)

logger = logging.getLogger(__name__)


def capture_learning_records(hours: int = 24, limit: int = 100) -> int:
    """Snapshot current state of recently scored events into LearningRecord."""
    since = timezone.now() - timezone.timedelta(hours=hours)

    events = Event.objects.filter(
        predictive_score__scored_at__gte=since,
    ).select_related("predictive_score").order_by("-importance_score")[:limit]

    created = 0
    for event in events:
        ps = event.predictive_score

        features = _extract_features(event)
        prediction_scores = _extract_prediction_scores(ps)
        anomaly_metrics = _extract_anomaly_metrics(event)
        feedback_summary = _extract_feedback_summary(event)
        outcome_data = _extract_outcome(ps)
        accuracy_label = outcome_data.get("accuracy_status", "")

        LearningRecord.objects.create(
            event=event,
            record_type="prediction_evaluation",
            features=features,
            prediction_scores=prediction_scores,
            anomaly_metrics=anomaly_metrics,
            feedback_summary=feedback_summary,
            outcome=outcome_data,
            accuracy_label=accuracy_label,
        )
        created += 1

    logger.info("Captured %d learning records", created)
    return created


def get_learning_stats() -> dict:
    """Statistics about learning data store."""
    total = LearningRecord.objects.count()
    by_type = dict(
        LearningRecord.objects.values_list("record_type")
        .annotate(c=Count("id"))
        .values_list("record_type", "c")
    )
    by_accuracy = dict(
        LearningRecord.objects.exclude(accuracy_label="")
        .values_list("accuracy_label")
        .annotate(c=Count("id"))
        .values_list("accuracy_label", "c")
    )
    return {
        "total_records": total,
        "by_type": by_type,
        "by_accuracy": by_accuracy,
        "latest_at": (
            LearningRecord.objects.order_by("-created_at")
            .values_list("created_at", flat=True)
            .first()
        ),
    }


def get_accuracy_history(days: int = 30, granularity: str = "day") -> list[dict]:
    """Return daily accuracy rates for charting."""
    since = timezone.now() - timezone.timedelta(days=days)
    records = LearningRecord.objects.filter(
        created_at__gte=since,
        accuracy_label__in=["accurate", "partially_accurate", "inaccurate"],
    ).order_by("created_at")

    from collections import defaultdict

    buckets: dict[str, dict] = defaultdict(lambda: {"accurate": 0, "partial": 0, "inaccurate": 0, "total": 0})

    for r in records:
        if granularity == "day":
            key = r.created_at.strftime("%Y-%m-%d")
        else:
            key = r.created_at.strftime("%Y-%m-%d %H:00")

        buckets[key]["total"] += 1
        if r.accuracy_label == "accurate":
            buckets[key]["accurate"] += 1
        elif r.accuracy_label == "partially_accurate":
            buckets[key]["partial"] += 1
        elif r.accuracy_label == "inaccurate":
            buckets[key]["inaccurate"] += 1

    result = []
    for date_key in sorted(buckets.keys()):
        b = buckets[date_key]
        t = b["total"]
        rate = (b["accurate"] + b["partial"] * 0.5) / t if t > 0 else 0
        result.append({
            "date": date_key,
            "total": t,
            "accurate": b["accurate"],
            "partial": b["partial"],
            "inaccurate": b["inaccurate"],
            "accuracy_rate": round(rate, 4),
        })
    return result


def _extract_features(event: Event) -> dict:
    return {
        "event_id": event.id,
        "event_type": event.event_type,
        "location_country": event.location_country,
        "source_count": event.source_count,
        "story_count": event.story_count,
        "importance_score": str(event.importance_score),
        "confidence_score": str(event.confidence_score),
        "conflict_flag": event.conflict_flag,
    }


def _extract_prediction_scores(ps: PredictiveScore) -> dict:
    return {
        "escalation_probability": str(ps.escalation_probability),
        "continuation_probability": str(ps.continuation_probability),
        "misleading_probability": str(ps.misleading_probability),
        "monitoring_priority": str(ps.monitoring_priority),
        "anomaly_factor": str(ps.anomaly_factor),
        "correlation_factor": str(ps.correlation_factor),
        "historical_factor": str(ps.historical_factor),
        "source_diversity_factor": str(ps.source_diversity_factor),
        "velocity_factor": str(ps.velocity_factor),
        "risk_trend": ps.risk_trend,
    }


def _extract_anomaly_metrics(event: Event) -> dict:
    anomalies = AnomalyDetection.objects.filter(
        Q(event=event) | Q(related_event_ids__contains=[event.id])
    )
    return {
        "total_anomalies": anomalies.count(),
        "by_type": dict(
            anomalies.values_list("anomaly_type")
            .annotate(c=Count("id"))
            .values_list("anomaly_type", "c")
        ),
        "by_severity": dict(
            anomalies.values_list("severity")
            .annotate(c=Count("id"))
            .values_list("severity", "c")
        ),
        "avg_deviation": float(
            anomalies.aggregate(a=Avg("deviation_factor"))["a"] or 0
        ),
    }


def _extract_feedback_summary(event: Event) -> dict:
    fb = AnalystFeedback.objects.filter(target_type="event", target_id=event.id)
    counts = dict(
        fb.values_list("feedback_type")
        .annotate(c=Count("id"))
        .values_list("feedback_type", "c")
    )
    return {
        "total": fb.count(),
        "by_type": counts,
    }


def _extract_outcome(ps: PredictiveScore) -> dict:
    try:
        outcome = OutcomeRecord.objects.get(
            target_type="prediction", target_id=ps.id,
        )
        return {
            "accuracy_status": outcome.accuracy_status,
            "actual_outcome": outcome.actual_outcome,
            "resolved_at": outcome.resolved_at.isoformat() if outcome.resolved_at else None,
        }
    except OutcomeRecord.DoesNotExist:
        return {}
