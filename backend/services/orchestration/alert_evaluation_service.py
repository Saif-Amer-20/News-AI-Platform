"""Alert Evaluation Service — evaluate articles against alert rules and create alerts.

Trigger logic
─────────────
1. **Keyword/watchlist match** — article matched keyword rules → create KEYWORD_MATCH alert.
2. **High-importance event** — article belongs to a high-importance event → STORY_UPDATE.
3. **Narrative conflict** — article belongs to a conflicted event → MANUAL_REVIEW.
4. **Low-confidence + high-importance** — event is important but unconfirmed → MANUAL_REVIEW.

Deduplication
─────────────
Each alert has a ``dedup_key`` built from (alert_type, topic_id, story_key).
If an open alert with the same dedup_key exists, we skip creation.
"""
from __future__ import annotations

import hashlib
import logging
from decimal import Decimal

from django.utils import timezone

from alerts.models import Alert, AlertEvent
from sources.models import Article, Event, Story

logger = logging.getLogger(__name__)


class AlertEvaluationService:
    """Evaluate an article and create alerts when criteria are met."""

    # Thresholds
    HIGH_IMPORTANCE_THRESHOLD = Decimal("0.70")
    LOW_CONFIDENCE_THRESHOLD = Decimal("0.30")
    KEYWORD_SEVERITY_MAP = {
        "critical": Alert.Severity.CRITICAL,
        "high": Alert.Severity.HIGH,
        "medium": Alert.Severity.MEDIUM,
        "low": Alert.Severity.LOW,
    }

    def evaluate(self, article: Article) -> list[Alert]:
        """Run all evaluation rules against the article.  Returns created alerts."""
        created: list[Alert] = []

        # Rule 1: Keyword/watchlist match alerts
        if article.matched_rule_labels:
            alert = self._keyword_match_alert(article)
            if alert:
                created.append(alert)

        story = article.story
        event = story.event if story and story.event_id else None

        # Rule 2: High-importance event story update
        if event and event.importance_score >= self.HIGH_IMPORTANCE_THRESHOLD:
            alert = self._story_update_alert(article, story, event)
            if alert:
                created.append(alert)

        # Rule 3: Narrative conflict detection
        if event and event.conflict_flag:
            alert = self._conflict_alert(article, story, event)
            if alert:
                created.append(alert)

        # Rule 4: Low confidence + high importance → manual review
        if (
            event
            and event.importance_score >= self.HIGH_IMPORTANCE_THRESHOLD
            and event.confidence_score <= self.LOW_CONFIDENCE_THRESHOLD
        ):
            alert = self._low_confidence_alert(article, story, event)
            if alert:
                created.append(alert)

        return created

    # ── Rule implementations ──────────────────────────────────────

    def _keyword_match_alert(self, article: Article) -> Alert | None:
        labels = article.matched_rule_labels or []
        if not labels:
            return None

        topic = article.matched_topics.first()
        dedup_key = self._dedup_key("keyword_match", topic, article)

        if self._alert_exists(dedup_key):
            return None

        # Determine severity from the highest-priority matched rule
        severity = self._severity_from_labels(article)

        alert = Alert.objects.create(
            title=f"Keyword match: {article.title[:120]}",
            alert_type=Alert.AlertType.KEYWORD_MATCH,
            severity=severity,
            summary=(
                f"Article matched rules: {', '.join(labels[:10])}. "
                f"Source: {article.source.name}."
            ),
            rationale=f"Matched {len(labels)} keyword rule(s) in topic monitoring.",
            dedup_key=dedup_key,
            topic=topic,
            source=article.source,
            metadata={
                "article_id": article.id,
                "matched_labels": labels[:20],
                "source_name": article.source.name,
            },
        )
        AlertEvent.objects.create(
            alert=alert,
            event_type=AlertEvent.EventType.CREATED,
            message=f"Auto-created from article {article.id}",
        )
        logger.info("Created keyword_match alert %s for article %s", alert.id, article.id)
        return alert

    def _story_update_alert(
        self, article: Article, story: Story, event: Event
    ) -> Alert | None:
        dedup_key = self._dedup_key("story_update", None, article, story)
        if self._alert_exists(dedup_key):
            return None

        alert = Alert.objects.create(
            title=f"High-importance update: {event.title[:120]}",
            alert_type=Alert.AlertType.STORY_UPDATE,
            severity=Alert.Severity.MEDIUM,
            summary=(
                f"New article in high-importance event (score={event.importance_score}). "
                f"Event: {event.title}. Source: {article.source.name}."
            ),
            rationale=(
                f"Event importance {event.importance_score} exceeds threshold "
                f"{self.HIGH_IMPORTANCE_THRESHOLD}."
            ),
            dedup_key=dedup_key,
            source=article.source,
            metadata={
                "article_id": article.id,
                "event_id": event.id,
                "story_id": story.id,
            },
        )
        AlertEvent.objects.create(
            alert=alert,
            event_type=AlertEvent.EventType.CREATED,
            message=f"Auto-created from article {article.id}",
        )
        return alert

    def _conflict_alert(
        self, article: Article, story: Story, event: Event
    ) -> Alert | None:
        dedup_key = self._dedup_key("conflict", None, article, event_obj=event)
        if self._alert_exists(dedup_key):
            return None

        alert = Alert.objects.create(
            title=f"Conflicting reports: {event.title[:120]}",
            alert_type=Alert.AlertType.MANUAL_REVIEW,
            severity=Alert.Severity.HIGH,
            summary=(
                f"Event has conflicting narratives across {event.source_count} sources. "
                f"Confidence: {event.confidence_score}."
            ),
            rationale="Narrative conflict detected — multiple sources report contradictory information.",
            dedup_key=dedup_key,
            source=article.source,
            metadata={
                "article_id": article.id,
                "event_id": event.id,
                "confidence_score": str(event.confidence_score),
            },
        )
        AlertEvent.objects.create(
            alert=alert,
            event_type=AlertEvent.EventType.CREATED,
            message=f"Auto-created — conflict detected for event {event.id}",
        )
        logger.warning("Created conflict alert %s for event %s", alert.id, event.id)
        return alert

    def _low_confidence_alert(
        self, article: Article, story: Story, event: Event
    ) -> Alert | None:
        dedup_key = self._dedup_key("low_confidence", None, article, event_obj=event)
        if self._alert_exists(dedup_key):
            return None

        alert = Alert.objects.create(
            title=f"Unconfirmed high-importance event: {event.title[:120]}",
            alert_type=Alert.AlertType.MANUAL_REVIEW,
            severity=Alert.Severity.MEDIUM,
            summary=(
                f"Event has high importance ({event.importance_score}) but low confidence "
                f"({event.confidence_score}). Only {event.source_count} source(s)."
            ),
            rationale=(
                f"Confidence {event.confidence_score} below threshold "
                f"{self.LOW_CONFIDENCE_THRESHOLD} while importance is high."
            ),
            dedup_key=dedup_key,
            source=article.source,
            metadata={
                "article_id": article.id,
                "event_id": event.id,
                "confidence_score": str(event.confidence_score),
                "importance_score": str(event.importance_score),
            },
        )
        AlertEvent.objects.create(
            alert=alert,
            event_type=AlertEvent.EventType.CREATED,
            message=f"Auto-created — low confidence event {event.id}",
        )
        return alert

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _dedup_key(
        alert_type: str,
        topic=None,
        article=None,
        story=None,
        event_obj=None,
    ) -> str:
        parts = [alert_type]
        if topic:
            parts.append(f"t{topic.id}")
        if story:
            parts.append(f"s{story.story_key}")
        elif event_obj:
            parts.append(f"e{event_obj.id}")
        if article:
            parts.append(f"a{article.content_hash[:16]}")
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:48]

    @staticmethod
    def _alert_exists(dedup_key: str) -> bool:
        return Alert.objects.filter(
            dedup_key=dedup_key,
            status__in=[Alert.Status.OPEN, Alert.Status.ACKNOWLEDGED, Alert.Status.INVESTIGATING],
        ).exists()

    def _severity_from_labels(self, article: Article) -> str:
        """Derive severity from matched topic keyword rules' priority."""
        try:
            from topics.models import KeywordRule

            labels = article.matched_rule_labels or []
            if not labels:
                return Alert.Severity.MEDIUM

            rules = KeywordRule.objects.filter(
                label__in=labels, enabled=True
            ).values_list("priority", flat=True)

            priority_order = ["critical", "high", "medium", "low"]
            for p in priority_order:
                if p in rules:
                    return self.KEYWORD_SEVERITY_MAP.get(p, Alert.Severity.MEDIUM)
        except Exception:
            pass
        return Alert.Severity.MEDIUM
