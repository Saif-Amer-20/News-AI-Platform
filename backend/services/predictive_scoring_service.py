"""Predictive Scoring Service for the Early Warning system.

Combines anomaly signals, signal correlations, historical patterns,
intel assessments, and event metadata into probabilistic scores:
  - escalation_probability
  - continuation_probability
  - misleading_probability
  - monitoring_priority

Uses a weighted factor model with optional LLM reasoning for top events.
All scores use probabilistic language and provide explainable breakdowns.
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Avg, Count, Q
from django.utils import timezone

from sources.models import (
    AnomalyDetection,
    Article,
    Event,
    EventIntelAssessment,
    HistoricalPattern,
    PredictiveScore,
    SignalCorrelation,
)

logger = logging.getLogger(__name__)


def score_event(event: Event) -> PredictiveScore:
    """Compute or update the predictive score for an event."""
    obj, _created = PredictiveScore.objects.get_or_create(
        event=event,
        defaults={"scored_at": timezone.now()},
    )

    try:
        # Gather input signals
        anomaly_factor = _compute_anomaly_factor(event)
        correlation_factor = _compute_correlation_factor(event)
        historical_factor = _compute_historical_factor(event)
        source_diversity_factor = _compute_source_diversity_factor(event)
        velocity_factor = _compute_velocity_factor(event)

        # Store factors
        obj.anomaly_factor = _safe_dec(anomaly_factor)
        obj.correlation_factor = _safe_dec(correlation_factor)
        obj.historical_factor = _safe_dec(historical_factor)
        obj.source_diversity_factor = _safe_dec(source_diversity_factor)
        obj.velocity_factor = _safe_dec(velocity_factor)

        # Composite scores (weighted combinations)
        obj.escalation_probability = _safe_dec(
            anomaly_factor * 0.30
            + correlation_factor * 0.20
            + historical_factor * 0.20
            + velocity_factor * 0.20
            + source_diversity_factor * 0.10
        )

        obj.continuation_probability = _safe_dec(
            velocity_factor * 0.35
            + source_diversity_factor * 0.25
            + anomaly_factor * 0.20
            + correlation_factor * 0.20
        )

        obj.misleading_probability = _safe_dec(
            _compute_misleading_factor(event, source_diversity_factor)
        )

        # Monitoring priority = max(esc, cont) weighted by anomaly count
        obj.monitoring_priority = _safe_dec(
            max(float(obj.escalation_probability), float(obj.continuation_probability)) * 0.60
            + anomaly_factor * 0.25
            + correlation_factor * 0.15
        )

        # Risk trend
        obj.risk_trend = _compute_risk_trend(event)

        # Weak signals summary
        obj.weak_signals = _gather_weak_signals(event)

        # Generate reasoning
        obj.reasoning = _build_reasoning(obj, event)

        # Arabic translation
        _translate_reasoning(obj)

        obj.model_used = "algorithmic-v1"
        obj.scored_at = timezone.now()
        obj.save()
        logger.info("Predictive score computed for event %d: priority=%.2f", event.id, float(obj.monitoring_priority))

    except Exception as exc:
        logger.exception("Predictive scoring failed for event %d: %s", event.id, exc)

    return obj


def score_recent_events(hours: int = 12, limit: int = 100) -> int:
    """Score all events updated in the last N hours."""
    cutoff = timezone.now() - timedelta(hours=hours)
    events = Event.objects.filter(updated_at__gte=cutoff).order_by("-importance_score")[:limit]
    scored = 0
    for event in events:
        score_event(event)
        scored += 1
    return scored


# ---------------------------------------------------------------------------
# Factor computation
# ---------------------------------------------------------------------------

def _compute_anomaly_factor(event: Event) -> float:
    """Score based on recent anomalies linked to this event."""
    cutoff = timezone.now() - timedelta(hours=24)
    anomalies = AnomalyDetection.objects.filter(
        Q(event=event) | Q(related_event_ids__contains=[event.id]),
        detected_at__gte=cutoff,
        status=AnomalyDetection.Status.ACTIVE,
    )

    severity_weights = {"low": 0.2, "medium": 0.4, "high": 0.7, "critical": 1.0}
    total_weight = sum(severity_weights.get(a.severity, 0.3) for a in anomalies)

    # Normalize: 0 anomalies = 0, 5+ high-severity = ~1.0
    return min(1.0, total_weight / 3.0)


def _compute_correlation_factor(event: Event) -> float:
    """Score based on signal correlations involving this event."""
    cutoff = timezone.now() - timedelta(hours=24)
    correlations = SignalCorrelation.objects.filter(
        Q(event_a=event) | Q(event_b=event),
        detected_at__gte=cutoff,
    )

    strength_weights = {"weak": 0.2, "moderate": 0.5, "strong": 1.0}
    total_weight = sum(strength_weights.get(c.strength, 0.2) for c in correlations)
    return min(1.0, total_weight / 2.0)


def _compute_historical_factor(event: Event) -> float:
    """Score based on matched historical patterns."""
    patterns = HistoricalPattern.objects.filter(event=event)
    if not patterns.exists():
        return 0.0

    avg_similarity = patterns.aggregate(avg=Avg("similarity_score"))["avg"] or 0
    return min(1.0, float(avg_similarity))


def _compute_source_diversity_factor(event: Event) -> float:
    """Higher source diversity = higher continuation probability."""
    src_count = event.source_count or 0
    if src_count >= 10:
        return 0.9
    elif src_count >= 5:
        return 0.7
    elif src_count >= 3:
        return 0.5
    elif src_count >= 2:
        return 0.3
    return 0.1


def _compute_velocity_factor(event: Event) -> float:
    """Article publication velocity in recent hours vs. earlier."""
    now = timezone.now()
    recent_cutoff = now - timedelta(hours=6)
    earlier_cutoff = now - timedelta(hours=24)

    recent_count = Article.objects.filter(
        story__event=event,
        created_at__gte=recent_cutoff,
    ).count()

    earlier_count = Article.objects.filter(
        story__event=event,
        created_at__gte=earlier_cutoff,
        created_at__lt=recent_cutoff,
    ).count()

    if earlier_count == 0 and recent_count == 0:
        return 0.0
    if earlier_count == 0:
        return min(1.0, recent_count / 5.0)

    # Velocity ratio: recent_rate / earlier_rate
    recent_rate = recent_count / 6.0  # per hour
    earlier_rate = earlier_count / 18.0  # per hour
    ratio = recent_rate / max(earlier_rate, 0.1)

    if ratio >= 3.0:
        return 0.9
    elif ratio >= 2.0:
        return 0.7
    elif ratio >= 1.5:
        return 0.5
    elif ratio >= 1.0:
        return 0.3
    return 0.1


def _compute_misleading_factor(event: Event, source_diversity: float) -> float:
    """Estimate probability the signal is misleading/disinformation."""
    factors = []

    # Low source diversity + high volume = suspicious
    if source_diversity < 0.3:
        factors.append(0.3)

    # Conflict flag present = possible disinformation campaign
    if event.conflict_flag:
        factors.append(0.2)

    # Check intel assessment if exists
    try:
        intel = EventIntelAssessment.objects.get(event=event)
        if intel.status == "completed":
            cred = float(intel.credibility_score)
            if cred < 0.4:
                factors.append(0.3)
            elif cred < 0.6:
                factors.append(0.1)
    except EventIntelAssessment.DoesNotExist:
        pass

    return min(1.0, sum(factors))


def _compute_risk_trend(event: Event) -> str:
    """Determine if the event risk is rising, stable, or declining."""
    now = timezone.now()
    recent_cutoff = now - timedelta(hours=6)
    earlier_cutoff = now - timedelta(hours=24)

    recent_articles = Article.objects.filter(
        story__event=event, created_at__gte=recent_cutoff,
    ).count()

    earlier_articles = Article.objects.filter(
        story__event=event,
        created_at__gte=earlier_cutoff,
        created_at__lt=recent_cutoff,
    ).count()

    recent_anomalies = AnomalyDetection.objects.filter(
        Q(event=event) | Q(related_event_ids__contains=[event.id]),
        detected_at__gte=recent_cutoff,
        status=AnomalyDetection.Status.ACTIVE,
    ).count()

    # Article velocity rising + anomalies = rising risk
    if recent_articles > 0 and (recent_articles * 3 > earlier_articles or recent_anomalies > 0):
        return "rising"
    elif recent_articles == 0 and earlier_articles > 0:
        return "declining"
    return "stable"


def _gather_weak_signals(event: Event) -> list[dict]:
    """Collect weak signals from various sources for this event."""
    signals = []
    cutoff = timezone.now() - timedelta(hours=24)

    # From anomalies
    anomalies = AnomalyDetection.objects.filter(
        Q(event=event) | Q(related_event_ids__contains=[event.id]),
        detected_at__gte=cutoff,
        status=AnomalyDetection.Status.ACTIVE,
    )[:10]
    for a in anomalies:
        signals.append({
            "signal": a.title,
            "weight": float(a.confidence),
            "source": "anomaly",
            "severity": a.severity,
        })

    # From correlations
    correlations = SignalCorrelation.objects.filter(
        Q(event_a=event) | Q(event_b=event),
        detected_at__gte=cutoff,
    )[:5]
    for c in correlations:
        signals.append({
            "signal": c.title,
            "weight": float(c.correlation_score),
            "source": "correlation",
            "strength": c.strength,
        })

    # From historical patterns
    patterns = HistoricalPattern.objects.filter(event=event)[:3]
    for p in patterns:
        signals.append({
            "signal": f"Historical match: {p.pattern_name or 'unnamed'}",
            "weight": float(p.similarity_score),
            "source": "pattern",
        })

    return sorted(signals, key=lambda s: -s["weight"])[:15]


def _build_reasoning(obj: PredictiveScore, event: Event) -> str:
    """Build human-readable reasoning for the predictive score."""
    parts = []
    parts.append(f"Predictive analysis for: {event.title}")
    parts.append("")

    esc = float(obj.escalation_probability)
    cont = float(obj.continuation_probability)
    mis = float(obj.misleading_probability)
    pri = float(obj.monitoring_priority)

    parts.append(f"• Escalation probability: {esc:.0%}")
    parts.append(f"• Continuation probability: {cont:.0%}")
    parts.append(f"• Misleading signal probability: {mis:.0%}")
    parts.append(f"• Monitoring priority: {pri:.0%}")
    parts.append(f"• Risk trend: {obj.risk_trend}")
    parts.append("")

    parts.append("Factor breakdown:")
    parts.append(f"  - Anomaly signals: {float(obj.anomaly_factor):.0%}")
    parts.append(f"  - Signal correlations: {float(obj.correlation_factor):.0%}")
    parts.append(f"  - Historical patterns: {float(obj.historical_factor):.0%}")
    parts.append(f"  - Source diversity: {float(obj.source_diversity_factor):.0%}")
    parts.append(f"  - Article velocity: {float(obj.velocity_factor):.0%}")

    if obj.weak_signals:
        parts.append("")
        parts.append("Detected weak signals:")
        for ws in obj.weak_signals[:5]:
            parts.append(f"  ⚡ [{ws.get('source', '?')}] {ws.get('signal', '?')} (weight: {ws.get('weight', 0):.2f})")

    return "\n".join(parts)


def _translate_reasoning(obj: PredictiveScore) -> None:
    """Translate reasoning to Arabic."""
    try:
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source="en", target="ar")
        text = obj.reasoning
        if text and len(text) > 10:
            obj.reasoning_ar = translator.translate(text[:4500])
    except Exception as exc:
        logger.warning("Arabic translation failed for predictive score: %s", exc)


def _safe_dec(val, default="0.00") -> Decimal:
    """Clamp a float value to Decimal [0, 1]."""
    try:
        d = Decimal(str(round(float(val), 2)))
        return max(Decimal("0.00"), min(Decimal("1.00"), d))
    except Exception:
        return Decimal(default)
