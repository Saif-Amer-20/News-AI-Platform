"""Historical Pattern Matching Service.

Compares current events against older events to find historical
parallels based on:
  - event_type similarity
  - location match
  - entity overlap
  - source pattern similarity
  - temporal characteristics

Produces HistoricalPattern records that feed the predictive scoring engine.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q
from django.utils import timezone

from sources.models import (
    Article,
    ArticleEntity,
    Event,
    HistoricalPattern,
)

logger = logging.getLogger(__name__)

# Only match events older than this many days
MIN_HISTORY_AGE_DAYS = 14
# Minimum similarity to record
MIN_SIMILARITY = 0.35


def match_patterns_for_event(event: Event) -> list[HistoricalPattern]:
    """Find historical patterns for a single event."""
    cutoff = timezone.now() - timedelta(days=MIN_HISTORY_AGE_DAYS)

    # Candidate pool: same event_type, older than cutoff, resolved or completed
    candidates = (
        Event.objects.filter(
            event_type=event.event_type,
            created_at__lt=cutoff,
        )
        .exclude(id=event.id)
        .order_by("-importance_score")[:50]
    )

    # Build entity profile for current event
    current_entities = _get_event_entity_ids(event)

    results = []
    for candidate in candidates:
        sim = _compute_similarity(event, candidate, current_entities)
        if sim >= MIN_SIMILARITY:
            outcome = _describe_outcome(candidate)
            trajectory = _predict_trajectory(event, candidate, sim)

            pattern, created = HistoricalPattern.objects.update_or_create(
                event=event,
                matched_event=candidate,
                defaults={
                    "pattern_name": f"{candidate.event_type}: {candidate.title[:80]}",
                    "similarity_score": Decimal(str(round(sim, 2))),
                    "matching_dimensions": _get_matching_dimensions(event, candidate, current_entities),
                    "historical_outcome": outcome,
                    "predicted_trajectory": trajectory,
                    "confidence": Decimal(str(round(min(1.0, sim * 1.1), 2))),
                },
            )

            # Arabic translation
            _translate_pattern(pattern)
            if created or not pattern.predicted_trajectory_ar:
                pattern.save()

            results.append(pattern)

    logger.info(
        "Historical pattern matching for event %d: %d matches found.",
        event.id,
        len(results),
    )
    return results


def match_patterns_recent(hours: int = 12, limit: int = 50) -> int:
    """Match patterns for recently updated events."""
    cutoff = timezone.now() - timedelta(hours=hours)
    events = (
        Event.objects.filter(updated_at__gte=cutoff)
        .order_by("-importance_score")[:limit]
    )
    total = 0
    for event in events:
        patterns = match_patterns_for_event(event)
        total += len(patterns)
    return total


# ---------------------------------------------------------------------------
# Similarity computation
# ---------------------------------------------------------------------------

def _compute_similarity(
    current: Event,
    historical: Event,
    current_entities: set[int],
) -> float:
    """Weighted multi-dimensional similarity."""
    scores = {}

    # 1. Event type (exact match = 1.0, else 0.0 — already pre-filtered)
    scores["event_type"] = 1.0 if current.event_type == historical.event_type else 0.0

    # 2. Location match
    if current.location_country and historical.location_country:
        if current.location_country == historical.location_country:
            scores["location"] = 1.0
        else:
            scores["location"] = 0.0
    else:
        scores["location"] = 0.2  # neutral when unknown

    # 3. Entity overlap (Jaccard)
    hist_entities = _get_event_entity_ids(historical)
    if current_entities and hist_entities:
        overlap = current_entities & hist_entities
        union = current_entities | hist_entities
        scores["entity_overlap"] = len(overlap) / len(union) if union else 0.0
    else:
        scores["entity_overlap"] = 0.0

    # 4. Source count similarity
    src_a = current.source_count or 1
    src_b = historical.source_count or 1
    scores["source_pattern"] = 1.0 - min(1.0, abs(src_a - src_b) / max(src_a, src_b))

    # 5. Importance similarity
    imp_a = float(current.importance_score or 0)
    imp_b = float(historical.importance_score or 0)
    scores["importance"] = 1.0 - min(1.0, abs(imp_a - imp_b))

    # Weighted combination
    weights = {
        "event_type": 0.25,
        "location": 0.25,
        "entity_overlap": 0.25,
        "source_pattern": 0.15,
        "importance": 0.10,
    }

    total = sum(scores[k] * weights[k] for k in weights)
    return total


def _get_event_entity_ids(event: Event) -> set[int]:
    """Get entity IDs for articles under an event."""
    article_ids = list(
        Article.objects.filter(
            story__event=event,
            is_duplicate=False,
        ).values_list("id", flat=True)[:300]
    )
    if not article_ids:
        return set()
    return set(
        ArticleEntity.objects.filter(article_id__in=article_ids)
        .values_list("entity_id", flat=True)
        .distinct()
    )


def _get_matching_dimensions(
    current: Event,
    historical: Event,
    current_entities: set[int],
) -> list[str]:
    """List which dimensions matched."""
    dims = []
    if current.event_type == historical.event_type:
        dims.append("event_type")
    if (
        current.location_country
        and historical.location_country
        and current.location_country == historical.location_country
    ):
        dims.append("location")

    hist_entities = _get_event_entity_ids(historical)
    if current_entities and hist_entities:
        overlap = current_entities & hist_entities
        if len(overlap) >= 2:
            dims.append("entity_overlap")

    src_a = current.source_count or 1
    src_b = historical.source_count or 1
    if abs(src_a - src_b) / max(src_a, src_b) < 0.5:
        dims.append("source_pattern")

    return dims


def _describe_outcome(event: Event) -> str:
    """Describe what happened after the historical event."""
    parts = [f"Event type: {event.event_type}"]
    parts.append(f"Location: {event.location_name or event.location_country or 'Unknown'}")
    parts.append(f"Sources: {event.source_count}")
    parts.append(f"Importance: {float(event.importance_score):.2f}")

    if event.conflict_flag:
        parts.append("Had narrative conflicts.")

    # Check if intel assessment exists
    try:
        intel = event.intel_assessment
        if intel.status == "completed":
            parts.append(f"Credibility assessment: {float(intel.credibility_score):.2f}")
            if intel.summary:
                parts.append(f"Summary: {intel.summary[:200]}")
    except Exception:
        pass

    return " | ".join(parts)


def _predict_trajectory(
    current: Event,
    historical: Event,
    similarity: float,
) -> str:
    """Generate predicted trajectory based on historical precedent."""
    parts = []
    parts.append(
        f"Based on historical precedent (similarity: {similarity:.0%}), "
        f"this event follows a pattern similar to \"{historical.title[:80]}\"."
    )

    if historical.conflict_flag:
        parts.append(
            "The historical event showed narrative conflicts, suggesting "
            "possible disagreements or contested information."
        )

    if historical.source_count and historical.source_count >= 5:
        parts.append(
            f"The historical event was covered by {historical.source_count} sources, "
            "indicating sustained media attention."
        )

    imp = float(historical.importance_score or 0)
    if imp >= 0.7:
        parts.append(
            "The historical event had high importance, suggesting this event "
            "may also develop into a significant situation."
        )
    elif imp < 0.3:
        parts.append(
            "The historical event had low importance and may have subsided "
            "without major developments."
        )

    return " ".join(parts)


def _translate_pattern(pattern: HistoricalPattern) -> None:
    """Translate predicted trajectory to Arabic."""
    try:
        from deep_translator import GoogleTranslator
        translator = GoogleTranslator(source="en", target="ar")
        text = pattern.predicted_trajectory
        if text and len(text) > 10:
            pattern.predicted_trajectory_ar = translator.translate(text[:4500])
    except Exception as exc:
        logger.warning("Arabic translation failed for historical pattern: %s", exc)
