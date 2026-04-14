"""Adaptive Scoring Service — adjusts thresholds & weights from learning data.

Safety rules:
  - All changes are auditable via AdaptiveThreshold model
  - Changes are clamped within min_value/max_value bounds
  - Single cycle max change is limited
  - Supports rollback via version history
"""
from __future__ import annotations

import logging
from decimal import Decimal
from collections import defaultdict

from django.db.models import Count, Q, Avg
from django.utils import timezone

from sources.models import (
    AdaptiveThreshold,
    AnalystFeedback,
    OutcomeRecord,
    AnomalyDetection,
    LearningRecord,
)

logger = logging.getLogger(__name__)

# Max adjustment per learning cycle
MAX_ADJUSTMENT_RATIO = Decimal("0.10")  # 10% of current value

# Default parameter definitions (name, type, default, min, max)
DEFAULT_PARAMS = [
    # Anomaly thresholds
    ("anomaly.volume_spike_threshold", "anomaly_threshold", "2.0000", "0.5000", "5.0000"),
    ("anomaly.source_diversity_threshold", "anomaly_threshold", "2.0000", "0.5000", "5.0000"),
    ("anomaly.entity_surge_threshold", "anomaly_threshold", "2.5000", "0.5000", "6.0000"),
    ("anomaly.location_surge_threshold", "anomaly_threshold", "2.0000", "0.5000", "5.0000"),
    ("anomaly.narrative_shift_threshold", "anomaly_threshold", "1.5000", "0.3000", "4.0000"),
    # Predictive weights — escalation
    ("predict.esc_anomaly_weight", "predictive_weight", "0.3000", "0.0500", "0.6000"),
    ("predict.esc_correlation_weight", "predictive_weight", "0.2000", "0.0500", "0.5000"),
    ("predict.esc_historical_weight", "predictive_weight", "0.2000", "0.0500", "0.5000"),
    ("predict.esc_velocity_weight", "predictive_weight", "0.2000", "0.0500", "0.5000"),
    ("predict.esc_source_div_weight", "predictive_weight", "0.1000", "0.0500", "0.4000"),
    # Source trust weights
    ("source.positive_feedback_weight", "source_trust_weight", "0.0300", "0.0050", "0.0800"),
    ("source.negative_feedback_weight", "source_trust_weight", "0.0400", "0.0050", "0.0800"),
    # Escalation sensitivity
    ("escalation.high_threshold", "escalation_sensitivity", "0.7000", "0.4000", "0.9500"),
    ("escalation.critical_threshold", "escalation_sensitivity", "0.8500", "0.6000", "0.9800"),
]


def bootstrap_adaptive_thresholds() -> int:
    """Ensure all default thresholds exist. Returns count of newly created."""
    created = 0
    for name, ptype, default, min_v, max_v in DEFAULT_PARAMS:
        _, was_created = AdaptiveThreshold.objects.get_or_create(
            param_name=name,
            defaults={
                "param_type": ptype,
                "current_value": Decimal(default),
                "default_value": Decimal(default),
                "min_value": Decimal(min_v),
                "max_value": Decimal(max_v),
            },
        )
        if was_created:
            created += 1
    return created


def get_threshold(param_name: str) -> float:
    """Get current threshold value, falling back to default if not in DB."""
    try:
        t = AdaptiveThreshold.objects.get(param_name=param_name, is_active=True)
        return float(t.current_value)
    except AdaptiveThreshold.DoesNotExist:
        for name, _, default, _, _ in DEFAULT_PARAMS:
            if name == param_name:
                return float(Decimal(default))
        return 1.0


def run_adaptive_learning_cycle(days: int = 30) -> dict:
    """Main learning cycle: analyze feedback/outcomes and adjust thresholds."""
    since = timezone.now() - timezone.timedelta(days=days)
    adjustments = {}

    # 1. Adjust anomaly thresholds based on false positive rate
    anomaly_adjustments = _adjust_anomaly_thresholds(since)
    adjustments.update(anomaly_adjustments)

    # 2. Adjust predictive weights based on outcome accuracy
    weight_adjustments = _adjust_predictive_weights(since)
    adjustments.update(weight_adjustments)

    # 3. Adjust escalation sensitivity
    esc_adjustments = _adjust_escalation_sensitivity(since)
    adjustments.update(esc_adjustments)

    logger.info("Adaptive learning cycle complete: %d parameters adjusted", len(adjustments))
    return adjustments


def rollback_threshold(param_name: str) -> AdaptiveThreshold | None:
    """Rollback a threshold to its previous value."""
    try:
        t = AdaptiveThreshold.objects.get(param_name=param_name)
    except AdaptiveThreshold.DoesNotExist:
        return None

    if t.previous_value is None:
        return None

    old = t.current_value
    t.current_value = t.previous_value
    t.previous_value = old
    t.version += 1
    t.adjustment_reason = f"Rollback from v{t.version - 1}"
    t.save()

    logger.info("Rolled back %s: %s → %s", param_name, old, t.current_value)
    return t


def reset_threshold_to_default(param_name: str) -> AdaptiveThreshold | None:
    """Reset a threshold to its factory default."""
    try:
        t = AdaptiveThreshold.objects.get(param_name=param_name)
    except AdaptiveThreshold.DoesNotExist:
        return None

    t.previous_value = t.current_value
    t.current_value = t.default_value
    t.version += 1
    t.adjustment_reason = "Reset to factory default"
    t.save()
    return t


def get_all_thresholds() -> list[dict]:
    """Return all adaptive thresholds with status."""
    return list(
        AdaptiveThreshold.objects.values(
            "param_name", "param_type", "current_value", "previous_value",
            "default_value", "min_value", "max_value", "adjustment_reason",
            "version", "is_active", "updated_at",
        )
    )


def _adjust_anomaly_thresholds(since) -> dict:
    """If too many false positives for an anomaly type, raise the threshold."""
    adjustments = {}
    type_map = {
        "volume_spike": "anomaly.volume_spike_threshold",
        "source_diversity": "anomaly.source_diversity_threshold",
        "entity_surge": "anomaly.entity_surge_threshold",
        "location_surge": "anomaly.location_surge_threshold",
        "narrative_shift": "anomaly.narrative_shift_threshold",
    }

    for anomaly_type, param_name in type_map.items():
        # Get anomaly IDs of this type in period
        anomaly_ids = list(
            AnomalyDetection.objects.filter(
                anomaly_type=anomaly_type, created_at__gte=since,
            ).values_list("id", flat=True)
        )
        if len(anomaly_ids) < 5:
            continue

        # Count feedback on these anomalies
        fb = AnalystFeedback.objects.filter(
            target_type="anomaly", target_id__in=anomaly_ids,
        )
        fp_count = fb.filter(feedback_type="false_positive").count()
        confirmed_count = fb.filter(feedback_type__in=["confirmed", "useful"]).count()
        total = fb.count()

        if total < 3:
            continue

        fp_rate = fp_count / total
        # If FP rate > 40%, increase threshold; if < 15%, decrease
        if fp_rate > 0.40:
            delta = Decimal("0.1")
            reason = f"High FP rate {fp_rate:.2f} for {anomaly_type}"
        elif fp_rate < 0.15 and confirmed_count > fp_count:
            delta = Decimal("-0.05")
            reason = f"Low FP rate {fp_rate:.2f}, good signal for {anomaly_type}"
        else:
            continue

        _apply_adjustment(param_name, delta, reason)
        adjustments[param_name] = {"delta": str(delta), "reason": reason}

    return adjustments


def _adjust_predictive_weights(since) -> dict:
    """Adjust prediction weights based on which factors correlate with accuracy."""
    adjustments = {}
    resolved = OutcomeRecord.objects.filter(
        target_type="prediction",
        resolved_at__isnull=False,
        resolved_at__gte=since,
    )
    if resolved.count() < 10:
        return adjustments

    # Analyze which factor was highest for accurate vs inaccurate predictions
    accurate_ids = list(
        resolved.filter(accuracy_status__in=["accurate", "partially_accurate"])
        .values_list("target_id", flat=True)
    )
    inaccurate_ids = list(
        resolved.filter(accuracy_status="inaccurate")
        .values_list("target_id", flat=True)
    )

    if not accurate_ids or not inaccurate_ids:
        return adjustments

    # Average the learning records
    from sources.models import PredictiveScore

    accurate_scores = PredictiveScore.objects.filter(id__in=accurate_ids)
    inaccurate_scores = PredictiveScore.objects.filter(id__in=inaccurate_ids)

    factor_fields = [
        "anomaly_factor", "correlation_factor", "historical_factor",
        "source_diversity_factor", "velocity_factor",
    ]
    param_prefix = "predict.esc_"
    param_suffix_map = {
        "anomaly_factor": "anomaly_weight",
        "correlation_factor": "correlation_weight",
        "historical_factor": "historical_weight",
        "source_diversity_factor": "source_div_weight",
        "velocity_factor": "velocity_weight",
    }

    for field in factor_fields:
        avg_accurate = accurate_scores.aggregate(a=Avg(field))["a"]
        avg_inaccurate = inaccurate_scores.aggregate(a=Avg(field))["a"]

        if avg_accurate is None or avg_inaccurate is None:
            continue

        # If accurate predictions had higher value of this factor, boost its weight
        diff = float(avg_accurate) - float(avg_inaccurate)
        if abs(diff) < 0.05:
            continue

        param_name = param_prefix + param_suffix_map[field]
        if diff > 0:
            delta = Decimal("0.01")
            reason = f"{field} higher in accurate predictions (diff={diff:.3f})"
        else:
            delta = Decimal("-0.01")
            reason = f"{field} higher in inaccurate predictions (diff={diff:.3f})"

        _apply_adjustment(param_name, delta, reason)
        adjustments[param_name] = {"delta": str(delta), "reason": reason}

    return adjustments


def _adjust_escalation_sensitivity(since) -> dict:
    """Adjust escalation thresholds based on escalation feedback."""
    adjustments = {}
    fb = AnalystFeedback.objects.filter(
        created_at__gte=since,
        feedback_type__in=["escalated_correctly", "false_positive"],
        target_type__in=["event", "prediction"],
    )
    esc_correct = fb.filter(feedback_type="escalated_correctly").count()
    fp = fb.filter(feedback_type="false_positive").count()
    total = esc_correct + fp

    if total < 5:
        return adjustments

    # If too many FP escalations → raise threshold (be less sensitive)
    fp_rate = fp / total
    param = "escalation.high_threshold"
    if fp_rate > 0.50:
        delta = Decimal("0.02")
        reason = f"Escalation FP rate {fp_rate:.2f}, raising threshold"
    elif fp_rate < 0.20 and esc_correct > 5:
        delta = Decimal("-0.02")
        reason = f"Good escalation accuracy ({fp_rate:.2f} FP), lowering threshold"
    else:
        return adjustments

    _apply_adjustment(param, delta, reason)
    adjustments[param] = {"delta": str(delta), "reason": reason}
    return adjustments


def _apply_adjustment(param_name: str, delta: Decimal, reason: str):
    """Apply a clamped adjustment to a threshold."""
    try:
        t = AdaptiveThreshold.objects.get(param_name=param_name)
    except AdaptiveThreshold.DoesNotExist:
        return

    # Clamp delta to MAX_ADJUSTMENT_RATIO of current value
    max_delta = abs(t.current_value * MAX_ADJUSTMENT_RATIO)
    clamped = max(-max_delta, min(max_delta, delta))

    new_value = t.current_value + clamped
    new_value = max(t.min_value, min(t.max_value, new_value))

    if new_value == t.current_value:
        return

    t.previous_value = t.current_value
    t.current_value = new_value
    t.version += 1
    t.adjustment_reason = reason
    t.evidence = {
        "delta_requested": str(delta),
        "delta_applied": str(clamped),
        "timestamp": timezone.now().isoformat(),
    }
    t.save()

    logger.info("Adjusted %s: %s → %s (%s)", param_name, t.previous_value, new_value, reason)
