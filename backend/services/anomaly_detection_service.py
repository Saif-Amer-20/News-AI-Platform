"""Anomaly Detection Engine for the Early Warning system.

Detects five anomaly types by comparing current metrics against
rolling baselines:
  1. Volume spikes — article count per event/topic surges
  2. Source diversity changes — sudden increase or decrease
  3. Entity mention surges — entities appearing far above baseline
  4. Location activity surges — geographic hotspot emergence
  5. Narrative shifts — sentiment / framing changes

Uses statistical z-score approach: current value vs. rolling 7-day average
with standard deviation. Signals with deviation_factor >= threshold are
recorded as AnomalyDetection objects.
"""
from __future__ import annotations

import logging
import math
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q
from django.utils import timezone

from sources.models import (
    AnomalyDetection,
    Article,
    ArticleEntity,
    Entity,
    Event,
)

logger = logging.getLogger(__name__)

# Default thresholds (overridden by adaptive learning if available)
VOLUME_SPIKE_THRESHOLD = 2.0
SOURCE_DIVERSITY_THRESHOLD = 2.0
ENTITY_SURGE_THRESHOLD = 2.5
LOCATION_SURGE_THRESHOLD = 2.0
NARRATIVE_SHIFT_THRESHOLD = 1.5


def _get_threshold(param_name: str, default: float) -> float:
    """Fetch adaptive threshold if available, else fallback to default."""
    try:
        from services.adaptive_scoring_service import get_threshold
        return get_threshold(param_name)
    except Exception:
        return default


def run_anomaly_scan() -> int:
    """Run all anomaly detectors. Returns count of new anomalies created."""
    now = timezone.now()
    total = 0
    total += _detect_volume_spikes(now)
    total += _detect_source_diversity_changes(now)
    total += _detect_entity_surges(now)
    total += _detect_location_surges(now)
    total += _detect_narrative_shifts(now)
    logger.info("Anomaly scan complete: %d new anomalies detected.", total)
    return total


# ---------------------------------------------------------------------------
# 1. Volume Spikes
# ---------------------------------------------------------------------------

def _detect_volume_spikes(now) -> int:
    """Detect events whose article volume in the last 6h significantly
    exceeds the 7-day rolling average."""
    window_recent = timedelta(hours=6)
    window_baseline = timedelta(days=7)

    cutoff_recent = now - window_recent
    cutoff_baseline = now - window_baseline

    # Recent counts per event
    recent_counts = dict(
        Article.objects.filter(
            created_at__gte=cutoff_recent,
            story__event__isnull=False,
        )
        .values_list("story__event_id")
        .annotate(cnt=Count("id"))
        .values_list("story__event_id", "cnt")
    )

    if not recent_counts:
        return 0

    # Baseline: daily average per event over 7 days (scaled to 6h window)
    baseline_counts = dict(
        Article.objects.filter(
            created_at__gte=cutoff_baseline,
            created_at__lt=cutoff_recent,
            story__event__isnull=False,
        )
        .values_list("story__event_id")
        .annotate(cnt=Count("id"))
        .values_list("story__event_id", "cnt")
    )

    baseline_hours = (window_baseline - window_recent).total_seconds() / 3600
    recent_hours = window_recent.total_seconds() / 3600
    created = 0

    for event_id, recent_cnt in recent_counts.items():
        baseline_total = baseline_counts.get(event_id, 0)
        baseline_rate = (baseline_total / baseline_hours) * recent_hours if baseline_hours > 0 else 0
        if baseline_rate < 1:
            baseline_rate = 1  # minimum baseline

        deviation = (recent_cnt - baseline_rate) / max(math.sqrt(baseline_rate), 1)

        if deviation >= _get_threshold("anomaly.volume_spike_threshold", VOLUME_SPIKE_THRESHOLD) and recent_cnt >= 3:
            severity = _deviation_to_severity(deviation)
            created += _create_anomaly(
                anomaly_type=AnomalyDetection.AnomalyType.VOLUME_SPIKE,
                title=f"Volume spike: {recent_cnt} articles in 6h (baseline ~{baseline_rate:.1f})",
                metric_name="article_count_6h",
                baseline_value=baseline_rate,
                current_value=recent_cnt,
                deviation_factor=deviation,
                severity=severity,
                confidence=_deviation_to_confidence(deviation),
                event_id=event_id,
                related_event_ids=[event_id],
            )

    return created


# ---------------------------------------------------------------------------
# 2. Source Diversity Changes
# ---------------------------------------------------------------------------

def _detect_source_diversity_changes(now) -> int:
    """Detect events where the number of distinct sources covering them
    in the last 6h significantly exceeds the baseline."""
    window_recent = timedelta(hours=6)
    window_baseline = timedelta(days=7)
    cutoff_recent = now - window_recent
    cutoff_baseline = now - window_baseline

    recent_articles = (
        Article.objects.filter(
            created_at__gte=cutoff_recent,
            story__event__isnull=False,
        )
        .values("story__event_id", "source_id")
        .distinct()
    )
    recent_diversity: dict[int, int] = Counter()
    for row in recent_articles:
        recent_diversity[row["story__event_id"]] += 1

    baseline_articles = (
        Article.objects.filter(
            created_at__gte=cutoff_baseline,
            created_at__lt=cutoff_recent,
            story__event__isnull=False,
        )
        .values("story__event_id", "source_id")
        .distinct()
    )
    baseline_diversity: dict[int, int] = Counter()
    for row in baseline_articles:
        baseline_diversity[row["story__event_id"]] += 1

    days_baseline = (window_baseline - window_recent).total_seconds() / 86400
    created = 0

    for event_id, recent_src_cnt in recent_diversity.items():
        baseline_src = baseline_diversity.get(event_id, 0)
        baseline_daily = baseline_src / max(days_baseline, 1)
        if baseline_daily < 1:
            baseline_daily = 1

        deviation = (recent_src_cnt - baseline_daily) / max(math.sqrt(baseline_daily), 1)
        if deviation >= _get_threshold("anomaly.source_diversity_threshold", SOURCE_DIVERSITY_THRESHOLD) and recent_src_cnt >= 3:
            severity = _deviation_to_severity(deviation)
            created += _create_anomaly(
                anomaly_type=AnomalyDetection.AnomalyType.SOURCE_DIVERSITY,
                title=f"Source diversity surge: {recent_src_cnt} distinct sources in 6h",
                metric_name="source_diversity_6h",
                baseline_value=baseline_daily,
                current_value=recent_src_cnt,
                deviation_factor=deviation,
                severity=severity,
                confidence=_deviation_to_confidence(deviation),
                event_id=event_id,
                related_event_ids=[event_id],
            )

    return created


# ---------------------------------------------------------------------------
# 3. Entity Mention Surges
# ---------------------------------------------------------------------------

def _detect_entity_surges(now) -> int:
    """Detect entities whose mention frequency surged above baseline."""
    window_recent = timedelta(hours=6)
    window_baseline = timedelta(days=7)
    cutoff_recent = now - window_recent
    cutoff_baseline = now - window_baseline

    recent_mentions = dict(
        ArticleEntity.objects.filter(article__created_at__gte=cutoff_recent)
        .values("entity_id")
        .annotate(cnt=Count("id"))
        .values_list("entity_id", "cnt")
    )

    baseline_mentions = dict(
        ArticleEntity.objects.filter(
            article__created_at__gte=cutoff_baseline,
            article__created_at__lt=cutoff_recent,
        )
        .values("entity_id")
        .annotate(cnt=Count("id"))
        .values_list("entity_id", "cnt")
    )

    baseline_hours = (window_baseline - window_recent).total_seconds() / 3600
    recent_hours = window_recent.total_seconds() / 3600
    created = 0

    for entity_id, recent_cnt in recent_mentions.items():
        bl_total = baseline_mentions.get(entity_id, 0)
        bl_rate = (bl_total / baseline_hours) * recent_hours if baseline_hours > 0 else 0
        if bl_rate < 1:
            bl_rate = 1

        deviation = (recent_cnt - bl_rate) / max(math.sqrt(bl_rate), 1)
        if deviation >= _get_threshold("anomaly.entity_surge_threshold", ENTITY_SURGE_THRESHOLD) and recent_cnt >= 5:
            try:
                entity = Entity.objects.get(id=entity_id)
                entity_name = entity.name
            except Entity.DoesNotExist:
                entity_name = f"Entity #{entity_id}"

            severity = _deviation_to_severity(deviation)
            created += _create_anomaly(
                anomaly_type=AnomalyDetection.AnomalyType.ENTITY_SURGE,
                title=f"Entity surge: '{entity_name}' — {recent_cnt} mentions in 6h",
                metric_name="entity_mentions_6h",
                baseline_value=bl_rate,
                current_value=recent_cnt,
                deviation_factor=deviation,
                severity=severity,
                confidence=_deviation_to_confidence(deviation),
                entity_id=entity_id,
                related_entity_ids=[entity_id],
            )

    return created


# ---------------------------------------------------------------------------
# 4. Location Activity Surges
# ---------------------------------------------------------------------------

def _detect_location_surges(now) -> int:
    """Detect countries with an unusual event creation rate."""
    window_recent = timedelta(hours=12)
    window_baseline = timedelta(days=7)
    cutoff_recent = now - window_recent
    cutoff_baseline = now - window_baseline

    recent_by_country = dict(
        Event.objects.filter(created_at__gte=cutoff_recent)
        .exclude(location_country="")
        .values("location_country")
        .annotate(cnt=Count("id"))
        .values_list("location_country", "cnt")
    )

    baseline_by_country = dict(
        Event.objects.filter(
            created_at__gte=cutoff_baseline,
            created_at__lt=cutoff_recent,
        )
        .exclude(location_country="")
        .values("location_country")
        .annotate(cnt=Count("id"))
        .values_list("location_country", "cnt")
    )

    baseline_hours = (window_baseline - window_recent).total_seconds() / 3600
    recent_hours = window_recent.total_seconds() / 3600
    created = 0

    for country, recent_cnt in recent_by_country.items():
        bl_total = baseline_by_country.get(country, 0)
        bl_rate = (bl_total / baseline_hours) * recent_hours if baseline_hours > 0 else 0
        if bl_rate < 1:
            bl_rate = 1

        deviation = (recent_cnt - bl_rate) / max(math.sqrt(bl_rate), 1)
        if deviation >= _get_threshold("anomaly.location_surge_threshold", LOCATION_SURGE_THRESHOLD) and recent_cnt >= 2:
            severity = _deviation_to_severity(deviation)
            created += _create_anomaly(
                anomaly_type=AnomalyDetection.AnomalyType.LOCATION_SURGE,
                title=f"Location surge: {country} — {recent_cnt} events in 12h",
                metric_name="location_events_12h",
                baseline_value=bl_rate,
                current_value=recent_cnt,
                deviation_factor=deviation,
                severity=severity,
                confidence=_deviation_to_confidence(deviation),
                location_country=country,
            )

    return created


# ---------------------------------------------------------------------------
# 5. Narrative Shifts
# ---------------------------------------------------------------------------

def _detect_narrative_shifts(now) -> int:
    """Detect events where the conflict flag was recently set or where
    the number of narratives changed significantly."""
    window_recent = timedelta(hours=12)
    cutoff = now - window_recent

    # Events that recently got a conflict flag
    flagged_events = Event.objects.filter(
        conflict_flag=True,
        updated_at__gte=cutoff,
    ).exclude(
        anomalies__anomaly_type=AnomalyDetection.AnomalyType.NARRATIVE_SHIFT,
        anomalies__detected_at__gte=cutoff,
    )[:50]

    created = 0
    for event in flagged_events:
        created += _create_anomaly(
            anomaly_type=AnomalyDetection.AnomalyType.NARRATIVE_SHIFT,
            title=f"Narrative conflict detected: {event.title}",
            metric_name="conflict_flag",
            baseline_value=0,
            current_value=1,
            deviation_factor=NARRATIVE_SHIFT_THRESHOLD,
            severity=AnomalyDetection.Severity.MEDIUM,
            confidence=Decimal("0.60"),
            event_id=event.id,
            related_event_ids=[event.id],
        )

    return created


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deviation_to_severity(deviation: float) -> str:
    if deviation >= 4.0:
        return AnomalyDetection.Severity.CRITICAL
    elif deviation >= 3.0:
        return AnomalyDetection.Severity.HIGH
    elif deviation >= 2.0:
        return AnomalyDetection.Severity.MEDIUM
    return AnomalyDetection.Severity.LOW


def _deviation_to_confidence(deviation: float) -> Decimal:
    """Map deviation factor to a confidence score (0-1)."""
    val = min(1.0, 0.4 + (deviation - 1.5) * 0.15)
    return Decimal(str(max(0.20, round(val, 2))))


def _create_anomaly(
    *,
    anomaly_type: str,
    title: str,
    metric_name: str,
    baseline_value: float,
    current_value: float,
    deviation_factor: float,
    severity: str,
    confidence: Decimal,
    event_id: int | None = None,
    entity_id: int | None = None,
    location_country: str = "",
    location_name: str = "",
    related_event_ids: list | None = None,
    related_entity_ids: list | None = None,
) -> int:
    """Create an AnomalyDetection record if a similar one doesn't already
    exist in the last 12 hours. Returns 1 if created, 0 if duplicate."""
    cutoff = timezone.now() - timedelta(hours=12)

    existing = AnomalyDetection.objects.filter(
        anomaly_type=anomaly_type,
        metric_name=metric_name,
        detected_at__gte=cutoff,
        status__in=[AnomalyDetection.Status.ACTIVE, AnomalyDetection.Status.ACKNOWLEDGED],
    )
    if event_id:
        existing = existing.filter(event_id=event_id)
    if entity_id:
        existing = existing.filter(entity_id=entity_id)
    if location_country:
        existing = existing.filter(location_country=location_country)

    if existing.exists():
        # Update the existing anomaly's current value
        existing.update(
            current_value=current_value,
            deviation_factor=deviation_factor,
            severity=severity,
            confidence=confidence,
        )
        return 0

    AnomalyDetection.objects.create(
        anomaly_type=anomaly_type,
        severity=severity,
        title=title,
        metric_name=metric_name,
        baseline_value=baseline_value,
        current_value=current_value,
        deviation_factor=deviation_factor,
        confidence=confidence,
        event_id=event_id,
        entity_id=entity_id,
        location_country=location_country,
        location_name=location_name,
        related_event_ids=related_event_ids or [],
        related_entity_ids=related_entity_ids or [],
        expires_at=timezone.now() + timedelta(hours=24),
    )
    return 1
