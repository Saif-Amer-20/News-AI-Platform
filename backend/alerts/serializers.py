"""DRF serializers for the Alerts domain."""
from __future__ import annotations

from rest_framework import serializers

from .models import Alert, AlertEvent


class AlertEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(
        source="actor.get_full_name", read_only=True, default=""
    )

    class Meta:
        model = AlertEvent
        fields = (
            "id",
            "event_type",
            "actor",
            "actor_name",
            "message",
            "data",
            "created_at",
        )


class AlertListSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source="source.name", read_only=True, default=None)
    topic_name = serializers.CharField(source="topic.name", read_only=True, default=None)

    class Meta:
        model = Alert
        fields = (
            "id",
            "title",
            "alert_type",
            "severity",
            "status",
            "source",
            "source_name",
            "topic",
            "topic_name",
            "triggered_at",
        )


class AlertDetailSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source="source.name", read_only=True, default=None)
    topic_name = serializers.CharField(source="topic.name", read_only=True, default=None)
    events = AlertEventSerializer(many=True, read_only=True)

    class Meta:
        model = Alert
        fields = (
            "id",
            "title",
            "alert_type",
            "severity",
            "status",
            "summary",
            "rationale",
            "dedup_key",
            "source",
            "source_name",
            "topic",
            "topic_name",
            "triggered_at",
            "acknowledged_at",
            "resolved_at",
            "events",
            "metadata",
            "created_at",
            "updated_at",
        )


class AlertAcknowledgeSerializer(serializers.Serializer):
    """Input for acknowledging an alert."""
    message = serializers.CharField(required=False, default="Acknowledged", max_length=2000)
