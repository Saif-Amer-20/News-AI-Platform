"""Early Warning & Predictive Intelligence API endpoints.

    GET   /api/v1/early-warning/anomalies/           — active anomalies
    GET   /api/v1/early-warning/correlations/         — signal correlations
    GET   /api/v1/early-warning/predictions/          — top predictive scores
    GET   /api/v1/early-warning/patterns/             — historical pattern matches
    GET   /api/v1/early-warning/geo-radar/            — active hot zones
    GET   /api/v1/early-warning/dashboard-summary/    — combined summary for dashboard
"""
from __future__ import annotations

import logging

from django.db.models import Count, Q
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import (
    AnomalyDetection,
    GeoRadarZone,
    HistoricalPattern,
    PredictiveScore,
    SignalCorrelation,
)
from .serializers import (
    AnomalyDetectionSerializer,
    GeoRadarZoneSerializer,
    HistoricalPatternSerializer,
    PredictiveScoreSerializer,
    SignalCorrelationSerializer,
)

logger = logging.getLogger(__name__)


class AnomalyDetectionViewSet(viewsets.ReadOnlyModelViewSet):
    """Active anomaly signals."""

    serializer_class = AnomalyDetectionSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["severity", "detected_at", "deviation_factor"]
    ordering = ["-detected_at"]

    def get_queryset(self):
        qs = AnomalyDetection.objects.all()
        status = self.request.query_params.get("status", "active")
        if status:
            qs = qs.filter(status=status)
        anomaly_type = self.request.query_params.get("type")
        if anomaly_type:
            qs = qs.filter(anomaly_type=anomaly_type)
        severity = self.request.query_params.get("severity")
        if severity:
            qs = qs.filter(severity=severity)
        event_id = self.request.query_params.get("event")
        if event_id:
            qs = qs.filter(Q(event_id=event_id) | Q(related_event_ids__contains=[int(event_id)]))
        return qs


class SignalCorrelationViewSet(viewsets.ReadOnlyModelViewSet):
    """Signal correlations across dimensions."""

    serializer_class = SignalCorrelationSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["correlation_score", "detected_at"]
    ordering = ["-correlation_score"]

    def get_queryset(self):
        qs = SignalCorrelation.objects.all()
        correlation_type = self.request.query_params.get("type")
        if correlation_type:
            qs = qs.filter(correlation_type=correlation_type)
        strength = self.request.query_params.get("strength")
        if strength:
            qs = qs.filter(strength=strength)
        event_id = self.request.query_params.get("event")
        if event_id:
            qs = qs.filter(Q(event_a_id=event_id) | Q(event_b_id=event_id))
        return qs


class PredictiveScoreViewSet(viewsets.ReadOnlyModelViewSet):
    """Predictive scores for events."""

    serializer_class = PredictiveScoreSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["monitoring_priority", "escalation_probability", "scored_at"]
    ordering = ["-monitoring_priority"]

    def get_queryset(self):
        qs = PredictiveScore.objects.select_related("event").all()
        min_priority = self.request.query_params.get("min_priority")
        if min_priority:
            qs = qs.filter(monitoring_priority__gte=min_priority)
        risk_trend = self.request.query_params.get("risk_trend")
        if risk_trend:
            qs = qs.filter(risk_trend=risk_trend)
        event_id = self.request.query_params.get("event")
        if event_id:
            qs = qs.filter(event_id=event_id)
        return qs


class HistoricalPatternViewSet(viewsets.ReadOnlyModelViewSet):
    """Historical pattern matches."""

    serializer_class = HistoricalPatternSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["similarity_score", "created_at"]
    ordering = ["-similarity_score"]

    def get_queryset(self):
        qs = HistoricalPattern.objects.select_related("event", "matched_event").all()
        event_id = self.request.query_params.get("event")
        if event_id:
            qs = qs.filter(event_id=event_id)
        min_similarity = self.request.query_params.get("min_similarity")
        if min_similarity:
            qs = qs.filter(similarity_score__gte=min_similarity)
        return qs


class GeoRadarZoneViewSet(viewsets.ReadOnlyModelViewSet):
    """Active geographic hot zones."""

    serializer_class = GeoRadarZoneSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["event_concentration", "event_count", "last_activity_at"]
    ordering = ["-event_concentration"]

    def get_queryset(self):
        qs = GeoRadarZone.objects.all()
        status = self.request.query_params.get("status", "active")
        if status:
            qs = qs.filter(status=status)
        country = self.request.query_params.get("country")
        if country:
            qs = qs.filter(location_country=country)
        return qs


class EarlyWarningDashboardViewSet(viewsets.ViewSet):
    """Combined Early Warning summary for the dashboard."""

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        """Aggregated early warning status for the dashboard widget."""
        anomalies = AnomalyDetection.objects.filter(status="active")
        correlations = SignalCorrelation.objects.all()
        predictions = PredictiveScore.objects.all()
        geo_zones = GeoRadarZone.objects.filter(status="active")

        # Top anomalies
        top_anomalies = AnomalyDetectionSerializer(
            anomalies.order_by("-severity", "-detected_at")[:5], many=True,
        ).data

        # Top predictions by monitoring priority
        top_predictions = PredictiveScoreSerializer(
            predictions.order_by("-monitoring_priority")[:5], many=True,
        ).data

        # Active correlations
        top_correlations = SignalCorrelationSerializer(
            correlations.order_by("-correlation_score")[:5], many=True,
        ).data

        # Hot zones
        hot_zones = GeoRadarZoneSerializer(
            geo_zones.order_by("-event_concentration")[:5], many=True,
        ).data

        # Aggregate stats
        anomaly_stats = {
            "total_active": anomalies.count(),
            "critical": anomalies.filter(severity="critical").count(),
            "high": anomalies.filter(severity="high").count(),
            "by_type": list(
                anomalies.values("anomaly_type")
                .annotate(count=Count("id"))
                .order_by("-count")
            ),
        }

        # Events with rising risk
        rising_events = predictions.filter(risk_trend="rising").count()

        return Response({
            "anomaly_stats": anomaly_stats,
            "rising_risk_events": rising_events,
            "active_hot_zones": geo_zones.count(),
            "active_correlations": correlations.count(),
            "top_anomalies": top_anomalies,
            "top_predictions": top_predictions,
            "top_correlations": top_correlations,
            "hot_zones": hot_zones,
        })
