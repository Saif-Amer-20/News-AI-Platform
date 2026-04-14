"""Self-Learning Intelligence Layer API endpoints.

    POST  /api/v1/learning/feedback/submit/             — submit analyst feedback
    GET   /api/v1/learning/feedback/                     — list feedback entries
    GET   /api/v1/learning/feedback/summary/             — summary for a target
    GET   /api/v1/learning/feedback/global-stats/        — platform-wide feedback stats

    POST  /api/v1/learning/outcomes/resolve/             — resolve an outcome
    GET   /api/v1/learning/outcomes/                     — list outcomes
    GET   /api/v1/learning/outcomes/accuracy-stats/      — accuracy stats

    GET   /api/v1/learning/reputation/                   — reputation change logs
    GET   /api/v1/learning/reputation/trend/             — trust trend for a source
    POST  /api/v1/learning/reputation/{id}/rollback/     — rollback a trust change

    GET   /api/v1/learning/thresholds/                   — list adaptive thresholds
    POST  /api/v1/learning/thresholds/{id}/rollback/     — rollback a threshold
    POST  /api/v1/learning/thresholds/{id}/reset/        — reset to default

    GET   /api/v1/learning/records/                      — learning data records
    GET   /api/v1/learning/records/stats/                — record stats
    GET   /api/v1/learning/records/accuracy-history/     — daily accuracy chart data

    GET   /api/v1/learning/dashboard/summary/            — combined learning summary
"""
from __future__ import annotations

import logging

from rest_framework import filters, status as http_status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import (
    AdaptiveThreshold,
    AnalystFeedback,
    LearningRecord,
    OutcomeRecord,
    SourceReputationLog,
)
from .serializers import (
    AdaptiveThresholdSerializer,
    AnalystFeedbackCreateSerializer,
    AnalystFeedbackSerializer,
    LearningRecordSerializer,
    OutcomeRecordSerializer,
    OutcomeResolveSerializer,
    SourceReputationLogSerializer,
)

logger = logging.getLogger(__name__)


# ─── Feedback ──────────────────────────────────────────────────


class FeedbackViewSet(viewsets.ReadOnlyModelViewSet):
    """Analyst feedback on alerts, events, predictions, cases, anomalies."""

    serializer_class = AnalystFeedbackSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["created_at", "feedback_type"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = AnalystFeedback.objects.select_related("analyst").all()
        target_type = self.request.query_params.get("target_type")
        target_id = self.request.query_params.get("target_id")
        feedback_type = self.request.query_params.get("feedback_type")
        if target_type:
            qs = qs.filter(target_type=target_type)
        if target_id:
            qs = qs.filter(target_id=target_id)
        if feedback_type:
            qs = qs.filter(feedback_type=feedback_type)
        return qs

    @action(detail=False, methods=["post"])
    def submit(self, request):
        """Submit analyst feedback."""
        ser = AnalystFeedbackCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        from services.feedback_service import submit_feedback

        fb = submit_feedback(
            target_type=ser.validated_data["target_type"],
            target_id=ser.validated_data["target_id"],
            feedback_type=ser.validated_data["feedback_type"],
            comment=ser.validated_data.get("comment", ""),
            analyst=request.user if request.user.is_authenticated else None,
            confidence=ser.validated_data.get("confidence", 1.00),
        )
        return Response(
            AnalystFeedbackSerializer(fb).data,
            status=http_status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Feedback summary for a specific target."""
        target_type = request.query_params.get("target_type")
        target_id = request.query_params.get("target_id")
        if not target_type or not target_id:
            return Response(
                {"error": "target_type and target_id are required."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        from services.feedback_service import get_feedback_summary

        data = get_feedback_summary(target_type, int(target_id))
        return Response(data)

    @action(detail=False, methods=["get"], url_path="global-stats")
    def global_stats(self, request):
        """Platform-wide feedback stats."""
        from services.feedback_service import get_feedback_stats_global

        days = int(request.query_params.get("days", 30))
        data = get_feedback_stats_global(days=days)
        return Response(data)


# ─── Outcomes ──────────────────────────────────────────────────


class OutcomeViewSet(viewsets.ReadOnlyModelViewSet):
    """Outcome tracking for predictions and early warnings."""

    serializer_class = OutcomeRecordSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["created_at", "resolved_at", "accuracy_status"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = OutcomeRecord.objects.all()
        target_type = self.request.query_params.get("target_type")
        target_id = self.request.query_params.get("target_id")
        accuracy_status = self.request.query_params.get("accuracy_status")
        if target_type:
            qs = qs.filter(target_type=target_type)
        if target_id:
            qs = qs.filter(target_id=target_id)
        if accuracy_status:
            qs = qs.filter(accuracy_status=accuracy_status)
        return qs

    @action(detail=False, methods=["post"])
    def resolve(self, request):
        """Manually resolve an outcome."""
        ser = OutcomeResolveSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        from services.outcome_tracking_service import resolve_outcome

        record = resolve_outcome(
            target_type=ser.validated_data["target_type"],
            target_id=ser.validated_data["target_id"],
            actual_outcome=ser.validated_data["actual_outcome"],
            accuracy_status=ser.validated_data["accuracy_status"],
            resolution_notes=ser.validated_data.get("resolution_notes", ""),
        )
        if record is None:
            return Response(
                {"error": "No pending outcome found for this target."},
                status=http_status.HTTP_404_NOT_FOUND,
            )
        return Response(OutcomeRecordSerializer(record).data)

    @action(detail=False, methods=["get"], url_path="accuracy-stats")
    def accuracy_stats(self, request):
        """Accuracy statistics across all outcomes."""
        from services.outcome_tracking_service import get_accuracy_stats

        days = int(request.query_params.get("days", 30))
        data = get_accuracy_stats(days=days)
        return Response(data)


# ─── Source Reputation ─────────────────────────────────────────


class SourceReputationViewSet(viewsets.ReadOnlyModelViewSet):
    """Source reputation change logs."""

    serializer_class = SourceReputationLogSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["created_at", "change_delta"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = SourceReputationLog.objects.select_related("source").all()
        source_id = self.request.query_params.get("source")
        reason = self.request.query_params.get("reason")
        if source_id:
            qs = qs.filter(source_id=source_id)
        if reason:
            qs = qs.filter(reason=reason)
        return qs

    @action(detail=False, methods=["get"])
    def trend(self, request):
        """Trust trend for a specific source."""
        source_id = request.query_params.get("source")
        if not source_id:
            return Response(
                {"error": "source query parameter is required."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        from services.source_reputation_service import get_source_trust_trend

        limit = int(request.query_params.get("limit", 20))
        data = get_source_trust_trend(int(source_id), limit=limit)
        return Response({"results": data})

    @action(detail=True, methods=["post"])
    def rollback(self, request, pk=None):
        """Rollback a specific trust change."""
        from services.source_reputation_service import rollback_trust_change

        user = request.user if request.user.is_authenticated else None
        result = rollback_trust_change(int(pk), user=user)
        if result is None:
            return Response(
                {"error": "Reputation log not found or already rolled back."},
                status=http_status.HTTP_404_NOT_FOUND,
            )
        return Response(SourceReputationLogSerializer(result).data)


# ─── Adaptive Thresholds ──────────────────────────────────────


class AdaptiveThresholdViewSet(viewsets.ReadOnlyModelViewSet):
    """Adaptive system thresholds / weights."""

    serializer_class = AdaptiveThresholdSerializer
    queryset = AdaptiveThreshold.objects.all()
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["param_name", "param_type", "updated_at"]
    ordering = ["param_name"]

    @action(detail=True, methods=["post"])
    def rollback(self, request, pk=None):
        """Rollback threshold to previous version."""
        threshold = self.get_object()
        from services.adaptive_scoring_service import rollback_threshold

        result = rollback_threshold(threshold.param_name)
        if result is None:
            return Response(
                {"error": "No previous value to rollback to."},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        return Response(AdaptiveThresholdSerializer(result).data)

    @action(detail=True, methods=["post"])
    def reset(self, request, pk=None):
        """Reset threshold to factory default."""
        threshold = self.get_object()
        from services.adaptive_scoring_service import reset_threshold_to_default

        result = reset_threshold_to_default(threshold.param_name)
        if result is None:
            return Response(
                {"error": "No default found for this threshold."},
                status=http_status.HTTP_404_NOT_FOUND,
            )
        return Response(AdaptiveThresholdSerializer(result).data)


# ─── Learning Records ─────────────────────────────────────────


class LearningRecordViewSet(viewsets.ReadOnlyModelViewSet):
    """Learning data store records."""

    serializer_class = LearningRecordSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["created_at", "record_type", "accuracy_label"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = LearningRecord.objects.all()
        record_type = self.request.query_params.get("record_type")
        accuracy_label = self.request.query_params.get("accuracy_label")
        if record_type:
            qs = qs.filter(record_type=record_type)
        if accuracy_label:
            qs = qs.filter(accuracy_label=accuracy_label)
        return qs

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Learning record statistics."""
        from services.learning_data_service import get_learning_stats

        data = get_learning_stats()
        return Response(data)

    @action(detail=False, methods=["get"], url_path="accuracy-history")
    def accuracy_history(self, request):
        """Daily accuracy rates for charts."""
        from services.learning_data_service import get_accuracy_history

        days = int(request.query_params.get("days", 30))
        granularity = request.query_params.get("granularity", "day")
        data = get_accuracy_history(days=days, granularity=granularity)
        return Response({"results": data})


# ─── Learning Dashboard ───────────────────────────────────────


class LearningDashboardViewSet(viewsets.ViewSet):
    """Combined self-learning summary for the dashboard."""

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        """Aggregated learning layer status."""
        from services.feedback_service import get_feedback_stats_global
        from services.outcome_tracking_service import get_accuracy_stats
        from services.learning_data_service import get_learning_stats, get_accuracy_history

        feedback_stats = get_feedback_stats_global(days=30)
        accuracy_stats = get_accuracy_stats(days=30)
        learning_stats = get_learning_stats()
        accuracy_history = get_accuracy_history(days=14, granularity="day")

        # Recent reputation changes
        recent_reputation = SourceReputationLogSerializer(
            SourceReputationLog.objects.select_related("source")
            .order_by("-created_at")[:5],
            many=True,
        ).data

        # Active thresholds
        thresholds = AdaptiveThresholdSerializer(
            AdaptiveThreshold.objects.filter(is_active=True).order_by("param_name"),
            many=True,
        ).data

        return Response({
            "feedback_stats": feedback_stats,
            "accuracy_stats": accuracy_stats,
            "learning_stats": learning_stats,
            "accuracy_history": accuracy_history,
            "recent_reputation_changes": recent_reputation,
            "active_thresholds": thresholds,
        })
