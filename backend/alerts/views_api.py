"""Public REST API viewsets for the Alerts domain."""
from __future__ import annotations

from django.db.models import Avg, Count, F, Q
from django.utils import timezone
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Alert, AlertEvent
from .serializers import (
    AlertAcknowledgeSerializer,
    AlertDetailSerializer,
    AlertListSerializer,
)


class AlertViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET  /api/v1/alerts/                        — list alerts
    GET  /api/v1/alerts/{id}/                   — alert detail with timeline
    GET  /api/v1/alerts/{id}/explain/           — full explainability
    POST /api/v1/alerts/{id}/acknowledge/       — acknowledge an alert
    POST /api/v1/alerts/{id}/resolve/           — resolve an alert
    POST /api/v1/alerts/{id}/dismiss/           — dismiss an alert
    POST /api/v1/alerts/{id}/escalate/          — escalate an alert
    POST /api/v1/alerts/{id}/comment/           — add a comment
    GET  /api/v1/alerts/stats/                  — alert statistics
    """

    queryset = Alert.objects.select_related("source", "topic").order_by("-triggered_at")
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["title", "summary"]
    ordering_fields = ["severity", "status", "triggered_at"]
    ordering = ["-triggered_at"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return AlertDetailSerializer
        return AlertListSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        alert_type = self.request.query_params.get("alert_type")
        severity = self.request.query_params.get("severity")
        alert_status = self.request.query_params.get("status")
        topic_id = self.request.query_params.get("topic")
        from_date = self.request.query_params.get("from_date")
        to_date = self.request.query_params.get("to_date")

        if alert_type:
            qs = qs.filter(alert_type=alert_type)
        if severity:
            qs = qs.filter(severity=severity)
        if alert_status:
            qs = qs.filter(status=alert_status)
        if topic_id:
            qs = qs.filter(topic_id=topic_id)
        if from_date:
            qs = qs.filter(triggered_at__gte=from_date)
        if to_date:
            qs = qs.filter(triggered_at__lte=to_date)
        return qs

    # ── Explainability ─────────────────────────────────────────────

    @action(detail=True, methods=["get"])
    def explain(self, request, pk=None):
        """Full explanation of why this alert was triggered.

        Returns the triggering article, event context, matched rules,
        confidence analysis, and recommended analyst actions.
        """
        alert = self.get_object()
        metadata = alert.metadata or {}
        explanation = {
            "alert_id": alert.id,
            "alert_type": alert.alert_type,
            "severity": alert.severity,
            "rationale": alert.rationale,
            "trigger_data": {},
            "context": {},
            "recommended_actions": [],
        }

        # Triggering article
        article_id = metadata.get("article_id")
        if article_id:
            from sources.models import Article
            try:
                article = Article.objects.select_related("source", "story").get(id=article_id)
                explanation["trigger_data"]["article"] = {
                    "id": article.id,
                    "title": article.title,
                    "url": article.url,
                    "source": article.source.name,
                    "published_at": article.published_at.isoformat() if article.published_at else None,
                    "quality_score": float(article.quality_score),
                    "importance_score": float(article.importance_score),
                }
            except Article.DoesNotExist:
                pass

        # Event context
        event_id = metadata.get("event_id")
        if event_id:
            from sources.models import Event
            try:
                event = Event.objects.get(id=event_id)
                source_names = list(
                    event.stories.values_list("articles__source__name", flat=True).distinct()[:10]
                )
                explanation["context"]["event"] = {
                    "id": event.id,
                    "title": event.title,
                    "event_type": event.event_type,
                    "location": event.location_name,
                    "country": event.location_country,
                    "confidence_score": float(event.confidence_score),
                    "importance_score": float(event.importance_score),
                    "conflict_flag": event.conflict_flag,
                    "story_count": event.story_count,
                    "source_count": event.source_count,
                    "sources": [s for s in source_names if s],
                    "timeline_length": len(event.timeline_json or []),
                }
            except Event.DoesNotExist:
                pass

        # Matched keyword rules
        matched_labels = metadata.get("matched_labels") or []
        if matched_labels:
            explanation["trigger_data"]["matched_rules"] = matched_labels
            if alert.topic:
                from topics.models import KeywordRule
                rules = KeywordRule.objects.filter(
                    topic=alert.topic,
                    label__in=matched_labels,
                    enabled=True,
                ).values("label", "pattern", "rule_type", "match_target", "priority")
                explanation["trigger_data"]["rule_details"] = list(rules)

        # Recommended actions based on alert type
        actions = []
        if alert.alert_type == Alert.AlertType.KEYWORD_MATCH:
            actions.append("Review the matched article to confirm relevance.")
            actions.append("Check if the keyword rules need refinement to reduce false positives.")
        elif alert.alert_type == Alert.AlertType.STORY_UPDATE:
            actions.append("Review the new article in the context of the ongoing story.")
            actions.append("Check if the event importance score is still accurate.")
        elif alert.alert_type == Alert.AlertType.MANUAL_REVIEW:
            if alert.severity in (Alert.Severity.HIGH, Alert.Severity.CRITICAL):
                actions.append("URGENT: Review conflicting narratives across sources.")
                actions.append("Cross-reference with trusted source(s) for verification.")
            else:
                actions.append("Review the event — low confidence may indicate emerging or unverified news.")
                actions.append("Monitor for additional source corroboration.")
        explanation["recommended_actions"] = actions

        # Similar alerts (same dedup pattern)
        if alert.dedup_key:
            similar = Alert.objects.filter(
                dedup_key=alert.dedup_key,
            ).exclude(id=alert.id).values("id", "title", "status", "triggered_at")[:10]
            explanation["context"]["similar_alerts"] = list(similar)

        return Response(explanation)

    # ── Lifecycle actions ──────────────────────────────────────────

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        alert = self.get_object()
        serializer = AlertAcknowledgeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        alert.status = Alert.Status.ACKNOWLEDGED
        alert.acknowledged_at = timezone.now()
        alert.acknowledged_by = request.user if request.user.is_authenticated else None
        alert.save(update_fields=["status", "acknowledged_at", "acknowledged_by", "updated_at"])

        AlertEvent.objects.create(
            alert=alert,
            event_type=AlertEvent.EventType.STATUS_CHANGED,
            actor=request.user if request.user.is_authenticated else None,
            message=serializer.validated_data.get("message", "Acknowledged"),
        )
        return Response({"status": "acknowledged"}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        alert = self.get_object()
        alert.status = Alert.Status.RESOLVED
        alert.resolved_at = timezone.now()
        alert.resolved_by = request.user if request.user.is_authenticated else None
        alert.save(update_fields=["status", "resolved_at", "resolved_by", "updated_at"])

        AlertEvent.objects.create(
            alert=alert,
            event_type=AlertEvent.EventType.STATUS_CHANGED,
            actor=request.user if request.user.is_authenticated else None,
            message=request.data.get("message", "Resolved"),
        )
        return Response({"status": "resolved"}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def dismiss(self, request, pk=None):
        alert = self.get_object()
        alert.status = Alert.Status.DISMISSED
        alert.resolved_at = timezone.now()
        alert.resolved_by = request.user if request.user.is_authenticated else None
        alert.save(update_fields=["status", "resolved_at", "resolved_by", "updated_at"])

        AlertEvent.objects.create(
            alert=alert,
            event_type=AlertEvent.EventType.STATUS_CHANGED,
            actor=request.user if request.user.is_authenticated else None,
            message=request.data.get("message", "Dismissed"),
        )
        return Response({"status": "dismissed"}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"])
    def escalate(self, request, pk=None):
        alert = self.get_object()
        if alert.severity == Alert.Severity.CRITICAL:
            return Response(
                {"error": "Already at maximum severity"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        severity_order = [
            Alert.Severity.LOW,
            Alert.Severity.MEDIUM,
            Alert.Severity.HIGH,
            Alert.Severity.CRITICAL,
        ]
        current_idx = severity_order.index(alert.severity)
        alert.severity = severity_order[current_idx + 1]
        alert.save(update_fields=["severity", "updated_at"])

        AlertEvent.objects.create(
            alert=alert,
            event_type=AlertEvent.EventType.ESCALATED,
            actor=request.user if request.user.is_authenticated else None,
            message=request.data.get("message", f"Escalated to {alert.severity}"),
        )
        return Response({"status": "escalated", "new_severity": alert.severity})

    @action(detail=True, methods=["post"])
    def comment(self, request, pk=None):
        alert = self.get_object()
        message = request.data.get("message", "")
        if not message:
            return Response({"error": "message is required"}, status=status.HTTP_400_BAD_REQUEST)

        event = AlertEvent.objects.create(
            alert=alert,
            event_type=AlertEvent.EventType.COMMENT,
            actor=request.user if request.user.is_authenticated else None,
            message=message[:2000],
        )
        return Response({"status": "commented", "event_id": event.id})

    # ── Statistics ─────────────────────────────────────────────────

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Alert statistics for dashboards."""
        qs = Alert.objects.all()
        from_date = request.query_params.get("from_date")
        to_date = request.query_params.get("to_date")
        if from_date:
            qs = qs.filter(triggered_at__gte=from_date)
        if to_date:
            qs = qs.filter(triggered_at__lte=to_date)

        by_status = dict(
            qs.values_list("status")
            .annotate(count=Count("id"))
            .values_list("status", "count")
        )
        by_severity = dict(
            qs.values_list("severity")
            .annotate(count=Count("id"))
            .values_list("severity", "count")
        )
        by_type = dict(
            qs.values_list("alert_type")
            .annotate(count=Count("id"))
            .values_list("alert_type", "count")
        )

        return Response({
            "total": qs.count(),
            "by_status": by_status,
            "by_severity": by_severity,
            "by_type": by_type,
            "open_critical": qs.filter(
                status=Alert.Status.OPEN,
                severity=Alert.Severity.CRITICAL,
            ).count(),
        })

    # ── Attach to case ─────────────────────────────────────────────

    @action(detail=True, methods=["post"], url_path="attach-case")
    def attach_case(self, request, pk=None):
        """Link this alert to an investigation case via CaseReference."""
        alert = self.get_object()
        case_id = request.data.get("case_id")
        if not case_id:
            return Response(
                {"error": "case_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from cases.models import Case, CaseReference

        try:
            case = Case.objects.get(id=case_id)
        except Case.DoesNotExist:
            return Response(
                {"error": "Case not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        obj, created = CaseReference.objects.get_or_create(
            case=case,
            reference_type="alert",
            target_app_label="alerts",
            target_model="alert",
            target_object_id=str(alert.id),
            defaults={
                "title": alert.title,
                "metadata": {
                    "alert_type": alert.alert_type,
                    "severity": alert.severity,
                    "status": alert.status,
                },
                "added_by": request.user if request.user.is_authenticated else None,
            },
        )

        AlertEvent.objects.create(
            alert=alert,
            event_type=AlertEvent.EventType.STATUS_CHANGED,
            actor=request.user if request.user.is_authenticated else None,
            message=f"Linked to case: {case.title}",
            data={"case_id": case.id, "case_title": case.title},
        )

        return Response(
            {
                "case_id": case.id,
                "alert_id": alert.id,
                "created": created,
                "reference_id": obj.id,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
