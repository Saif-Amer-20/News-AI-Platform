"""Signal Correlation Engine for the Early Warning system.

Finds cross-dimensional links between weak signals:
  - Cross-Event: Events sharing entities, locations, or time proximity
  - Cross-Entity: Entities co-occurring across multiple anomalies
  - Cross-Location: Geographic clusters of anomalies
  - Temporal: Signals bunching in narrow time windows
  - Source Pattern: Same source ecosystem amplifying unrelated events
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q
from django.utils import timezone

from sources.models import (
    AnomalyDetection,
    Article,
    ArticleEntity,
    Event,
    SignalCorrelation,
)

logger = logging.getLogger(__name__)

CORRELATION_THRESHOLD = 0.30  # minimum score to record


def run_signal_correlation() -> int:
    """Run all correlation detectors. Returns count of new correlations."""
    now = timezone.now()
    total = 0
    total += _correlate_cross_event(now)
    total += _correlate_cross_entity(now)
    total += _correlate_cross_location(now)
    total += _correlate_temporal(now)
    logger.info("Signal correlation complete: %d new correlations.", total)
    return total


# ---------------------------------------------------------------------------
# 1. Cross-Event Correlation
# ---------------------------------------------------------------------------

def _correlate_cross_event(now) -> int:
    """Find events that share significant entity overlap and have
    concurrent anomalies."""
    cutoff = now - timedelta(hours=24)

    # Get events with recent anomalies
    anomalous_events = list(
        AnomalyDetection.objects.filter(
            detected_at__gte=cutoff,
            status=AnomalyDetection.Status.ACTIVE,
            event__isnull=False,
        )
        .values_list("event_id", flat=True)
        .distinct()
    )

    if len(anomalous_events) < 2:
        return 0

    # Build entity profiles for these events
    event_entities: dict[int, set[int]] = defaultdict(set)
    for event_id in anomalous_events:
        article_ids = list(
            Article.objects.filter(
                story__event_id=event_id,
                is_duplicate=False,
            ).values_list("id", flat=True)[:200]
        )
        if article_ids:
            entity_ids = set(
                ArticleEntity.objects.filter(article_id__in=article_ids)
                .values_list("entity_id", flat=True)
                .distinct()
            )
            event_entities[event_id] = entity_ids

    created = 0
    seen_pairs: set[tuple] = set()

    for i, ev_a in enumerate(anomalous_events):
        for ev_b in anomalous_events[i + 1:]:
            pair = (min(ev_a, ev_b), max(ev_a, ev_b))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            entities_a = event_entities.get(ev_a, set())
            entities_b = event_entities.get(ev_b, set())
            if not entities_a or not entities_b:
                continue

            overlap = entities_a & entities_b
            union = entities_a | entities_b
            jaccard = len(overlap) / len(union) if union else 0

            if jaccard >= CORRELATION_THRESHOLD:
                # Also check if events share location
                try:
                    event_a_obj = Event.objects.get(id=ev_a)
                    event_b_obj = Event.objects.get(id=ev_b)
                except Event.DoesNotExist:
                    continue

                location_bonus = 0.15 if (
                    event_a_obj.location_country
                    and event_a_obj.location_country == event_b_obj.location_country
                ) else 0

                score = min(1.0, jaccard + location_bonus)
                strength = _score_to_strength(score)

                shared_entity_ids = list(overlap)[:20]
                created += _create_correlation(
                    correlation_type=SignalCorrelation.CorrelationType.CROSS_EVENT,
                    title=f"Cross-event link: events {ev_a} ↔ {ev_b} ({len(overlap)} shared entities)",
                    correlation_score=Decimal(str(round(score, 2))),
                    strength=strength,
                    event_a_id=ev_a,
                    event_b_id=ev_b,
                    entity_ids=shared_entity_ids,
                    reasoning=(
                        f"Entity overlap Jaccard={jaccard:.2f}, "
                        f"shared entities={len(overlap)}, "
                        f"same country={'Yes' if location_bonus else 'No'}."
                    ),
                    supporting_signals=[
                        {"signal_type": "entity_overlap", "detail": f"{len(overlap)} shared entities", "weight": jaccard},
                        {"signal_type": "location_match", "detail": event_a_obj.location_country or "N/A", "weight": location_bonus},
                    ],
                )

    return created


# ---------------------------------------------------------------------------
# 2. Cross-Entity Correlation
# ---------------------------------------------------------------------------

def _correlate_cross_entity(now) -> int:
    """Find entities that appear together across multiple recent anomalies."""
    cutoff = now - timedelta(hours=24)

    entity_anomalies = (
        AnomalyDetection.objects.filter(
            detected_at__gte=cutoff,
            status=AnomalyDetection.Status.ACTIVE,
            entity__isnull=False,
        )
        .values_list("entity_id", flat=True)
    )

    entity_counts = Counter(entity_anomalies)
    # Entities with 2+ anomalies are interesting
    hot_entities = [eid for eid, cnt in entity_counts.items() if cnt >= 2]

    if len(hot_entities) < 2:
        return 0

    # Check co-occurrence of hot entities in articles
    created = 0
    seen_pairs: set[tuple] = set()

    for i, ent_a in enumerate(hot_entities):
        articles_a = set(
            ArticleEntity.objects.filter(entity_id=ent_a)
            .values_list("article_id", flat=True)[:500]
        )
        for ent_b in hot_entities[i + 1:]:
            pair = (min(ent_a, ent_b), max(ent_a, ent_b))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            articles_b = set(
                ArticleEntity.objects.filter(entity_id=ent_b)
                .values_list("article_id", flat=True)[:500]
            )
            shared = articles_a & articles_b
            if len(shared) >= 3:
                score = min(1.0, len(shared) / 20.0 + 0.3)
                strength = _score_to_strength(score)
                created += _create_correlation(
                    correlation_type=SignalCorrelation.CorrelationType.CROSS_ENTITY,
                    title=f"Entity co-occurrence: entities {ent_a} ↔ {ent_b} in {len(shared)} articles",
                    correlation_score=Decimal(str(round(score, 2))),
                    strength=strength,
                    entity_ids=[ent_a, ent_b],
                    reasoning=f"Entities appear together in {len(shared)} articles, both have active anomalies.",
                    supporting_signals=[
                        {"signal_type": "co_occurrence", "detail": f"{len(shared)} shared articles", "weight": score},
                    ],
                )

    return created


# ---------------------------------------------------------------------------
# 3. Cross-Location Correlation
# ---------------------------------------------------------------------------

def _correlate_cross_location(now) -> int:
    """Find locations with multiple simultaneous anomalies."""
    cutoff = now - timedelta(hours=24)

    location_anomalies = (
        AnomalyDetection.objects.filter(
            detected_at__gte=cutoff,
            status=AnomalyDetection.Status.ACTIVE,
        )
        .exclude(location_country="")
        .values("location_country")
        .annotate(cnt=Count("id"))
        .filter(cnt__gte=2)
    )

    created = 0
    for entry in location_anomalies:
        country = entry["location_country"]
        cnt = entry["cnt"]
        score = min(1.0, cnt / 10.0 + 0.3)
        strength = _score_to_strength(score)

        anomaly_ids = list(
            AnomalyDetection.objects.filter(
                detected_at__gte=cutoff,
                status=AnomalyDetection.Status.ACTIVE,
                location_country=country,
            ).values_list("id", flat=True)[:20]
        )

        created += _create_correlation(
            correlation_type=SignalCorrelation.CorrelationType.CROSS_LOCATION,
            title=f"Location hotspot: {country} — {cnt} concurrent anomalies",
            correlation_score=Decimal(str(round(score, 2))),
            strength=strength,
            reasoning=f"{cnt} anomalies detected in {country} within 24h.",
            anomaly_ids=anomaly_ids,
            supporting_signals=[
                {"signal_type": "geographic_cluster", "detail": f"{cnt} anomalies in {country}", "weight": score},
            ],
        )

    return created


# ---------------------------------------------------------------------------
# 4. Temporal Correlation
# ---------------------------------------------------------------------------

def _correlate_temporal(now) -> int:
    """Find bursts of anomalies in narrow time windows (within 2h)."""
    cutoff = now - timedelta(hours=6)

    recent_anomalies = list(
        AnomalyDetection.objects.filter(
            detected_at__gte=cutoff,
            status=AnomalyDetection.Status.ACTIVE,
        )
        .order_by("detected_at")
        .values("id", "detected_at", "anomaly_type", "event_id")
    )

    if len(recent_anomalies) < 3:
        return 0

    # Sliding 2-hour window
    window = timedelta(hours=2)
    created = 0
    processed_windows: set[str] = set()

    for i, anchor in enumerate(recent_anomalies):
        cluster = [anchor]
        for j in range(i + 1, len(recent_anomalies)):
            if recent_anomalies[j]["detected_at"] - anchor["detected_at"] <= window:
                cluster.append(recent_anomalies[j])
            else:
                break

        if len(cluster) >= 3:
            types = set(a["anomaly_type"] for a in cluster)
            # Only interesting if multiple anomaly types cluster together
            if len(types) >= 2:
                window_key = f"{anchor['detected_at'].isoformat()[:13]}_{len(cluster)}"
                if window_key in processed_windows:
                    continue
                processed_windows.add(window_key)

                anomaly_ids = [a["id"] for a in cluster]
                score = min(1.0, len(cluster) / 8.0 + 0.3)
                strength = _score_to_strength(score)

                created += _create_correlation(
                    correlation_type=SignalCorrelation.CorrelationType.TEMPORAL,
                    title=f"Temporal burst: {len(cluster)} anomalies ({len(types)} types) within 2h",
                    correlation_score=Decimal(str(round(score, 2))),
                    strength=strength,
                    reasoning=f"{len(cluster)} anomalies of types {', '.join(types)} detected within a 2-hour window.",
                    anomaly_ids=anomaly_ids,
                    supporting_signals=[
                        {"signal_type": "temporal_cluster", "detail": f"{len(cluster)} in 2h", "weight": score},
                    ],
                )

    return created


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _score_to_strength(score: float) -> str:
    if score >= 0.7:
        return SignalCorrelation.Strength.STRONG
    elif score >= 0.45:
        return SignalCorrelation.Strength.MODERATE
    return SignalCorrelation.Strength.WEAK


def _create_correlation(
    *,
    correlation_type: str,
    title: str,
    correlation_score: Decimal,
    strength: str,
    event_a_id: int | None = None,
    event_b_id: int | None = None,
    entity_ids: list | None = None,
    anomaly_ids: list | None = None,
    reasoning: str = "",
    evidence: dict | None = None,
    supporting_signals: list | None = None,
) -> int:
    """Create a SignalCorrelation if similar doesn't exist in last 12h."""
    cutoff = timezone.now() - timedelta(hours=12)

    existing = SignalCorrelation.objects.filter(
        correlation_type=correlation_type,
        detected_at__gte=cutoff,
    )
    if event_a_id and event_b_id:
        existing = existing.filter(
            Q(event_a_id=event_a_id, event_b_id=event_b_id)
            | Q(event_a_id=event_b_id, event_b_id=event_a_id)
        )

    if existing.exists():
        existing.update(
            correlation_score=correlation_score,
            strength=strength,
        )
        return 0

    SignalCorrelation.objects.create(
        correlation_type=correlation_type,
        strength=strength,
        title=title,
        correlation_score=correlation_score,
        event_a_id=event_a_id,
        event_b_id=event_b_id,
        entity_ids=entity_ids or [],
        anomaly_ids=anomaly_ids or [],
        reasoning=reasoning,
        evidence=evidence or {},
        supporting_signals=supporting_signals or [],
    )
    return 1
