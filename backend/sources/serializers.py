"""DRF serializers for the Sources domain."""
from __future__ import annotations

from rest_framework import serializers

from .models import (
    AdaptiveThreshold,
    AnalystFeedback,
    AnomalyDetection,
    Article,
    ArticleAISummary,
    ArticleEntity,
    ArticleTranslation,
    Entity,
    Event,
    EventIntelAssessment,
    GeoRadarZone,
    HistoricalPattern,
    LearningRecord,
    OutcomeRecord,
    PredictiveScore,
    RawItem,
    SignalCorrelation,
    Source,
    SourceFetchRun,
    SourceReputationLog,
    Story,
)


class ProcessRawItemSerializer(serializers.Serializer):
    raw_item_id = serializers.IntegerField(min_value=1)
    sync = serializers.BooleanField(default=False)


# ── Source ────────────────────────────────────────────────────────────────────


class SourceListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Source
        fields = (
            "id",
            "name",
            "slug",
            "source_type",
            "parser_type",
            "base_url",
            "country",
            "language",
            "trust_score",
            "is_active",
            "status",
            "health_status",
            "total_articles_fetched",
            "avg_quality_score",
            "last_checked_at",
            "last_success_at",
        )


class SourceDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Source
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "source_type",
            "parser_type",
            "base_url",
            "endpoint_url",
            "country",
            "language",
            "trust_score",
            "is_active",
            "status",
            "health_status",
            "fetch_interval_minutes",
            "total_articles_fetched",
            "total_duplicates",
            "total_low_quality",
            "avg_quality_score",
            "last_checked_at",
            "last_success_at",
            "last_failure_at",
            "last_error_message",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "trust_score",
            "total_articles_fetched",
            "total_duplicates",
            "total_low_quality",
            "avg_quality_score",
            "health_status",
            "last_checked_at",
            "last_success_at",
            "last_failure_at",
            "last_error_message",
        )


class SourceFetchRunSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source="source.name", read_only=True)

    class Meta:
        model = SourceFetchRun
        fields = (
            "id",
            "source",
            "source_name",
            "started_at",
            "finished_at",
            "status",
            "items_fetched",
            "items_created",
        )


# ── Entity ───────────────────────────────────────────────────────────────────


class EntitySerializer(serializers.ModelSerializer):
    article_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Entity
        fields = (
            "id",
            "name",
            "normalized_name",
            "canonical_name",
            "aliases",
            "entity_type",
            "country",
            "latitude",
            "longitude",
            "article_count",
            "created_at",
        )


class ArticleEntitySerializer(serializers.ModelSerializer):
    entity = EntitySerializer(read_only=True)

    class Meta:
        model = ArticleEntity
        fields = ("id", "entity", "relevance_score", "mention_count", "context_snippet")


# ── Article ──────────────────────────────────────────────────────────────────


class ArticleListSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source="source.name", read_only=True)
    story_title = serializers.CharField(source="story.title", read_only=True, default=None)

    class Meta:
        model = Article
        fields = (
            "id",
            "title",
            "url",
            "source",
            "source_name",
            "story",
            "story_title",
            "published_at",
            "is_duplicate",
            "quality_score",
            "importance_score",
            "created_at",
        )


class ArticleTranslationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ArticleTranslation
        fields = (
            "id",
            "language_code",
            "translated_title",
            "translated_body",
            "translation_status",
            "translated_at",
            "provider",
            "error_message",
            "created_at",
        )
        read_only_fields = fields


class ArticleAISummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = ArticleAISummary
        fields = (
            "id",
            "summary",
            "predictions",
            "summary_ar",
            "predictions_ar",
            "model_used",
            "status",
            "generated_at",
            "error_message",
            "created_at",
        )
        read_only_fields = fields


class ArticleDetailSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source="source.name", read_only=True)
    story_title = serializers.CharField(source="story.title", read_only=True, default=None)
    entities = ArticleEntitySerializer(source="article_entities", many=True, read_only=True)
    matched_topic_names = serializers.SerializerMethodField()
    translations = ArticleTranslationSerializer(many=True, read_only=True)
    ai_summary = ArticleAISummarySerializer(read_only=True)

    class Meta:
        model = Article
        fields = (
            "id",
            "title",
            "normalized_title",
            "url",
            "canonical_url",
            "content",
            "author",
            "image_url",
            "source",
            "source_name",
            "story",
            "story_title",
            "published_at",
            "is_duplicate",
            "content_hash",
            "quality_score",
            "importance_score",
            "matched_rule_labels",
            "entities",
            "matched_topic_names",
            "translations",
            "ai_summary",
            "metadata",
            "created_at",
            "updated_at",
        )

    def get_matched_topic_names(self, obj):
        return list(obj.matched_topics.values_list("name", flat=True))


# ── Story ────────────────────────────────────────────────────────────────────


class StoryListSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(source="event.title", read_only=True, default=None)

    class Meta:
        model = Story
        fields = (
            "id",
            "title",
            "slug",
            "story_key",
            "article_count",
            "importance_score",
            "event",
            "event_title",
            "first_published_at",
            "last_published_at",
        )


class StoryDetailSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(source="event.title", read_only=True, default=None)
    articles = ArticleListSerializer(many=True, read_only=True)

    class Meta:
        model = Story
        fields = (
            "id",
            "title",
            "slug",
            "story_key",
            "article_count",
            "importance_score",
            "event",
            "event_title",
            "first_published_at",
            "last_published_at",
            "articles",
            "created_at",
            "updated_at",
        )


# ── Event ────────────────────────────────────────────────────────────────────


class EventListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = (
            "id",
            "title",
            "slug",
            "event_type",
            "location_name",
            "location_country",
            "story_count",
            "source_count",
            "confidence_score",
            "geo_confidence",
            "conflict_flag",
            "importance_score",
            "first_reported_at",
            "last_reported_at",
        )


class EventDetailSerializer(serializers.ModelSerializer):
    stories = StoryListSerializer(many=True, read_only=True)
    source_correlation = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = (
            "id",
            "title",
            "slug",
            "description",
            "event_type",
            "location_name",
            "location_country",
            "location_lat",
            "location_lon",
            "story_count",
            "source_count",
            "confidence_score",
            "geo_confidence",
            "conflict_flag",
            "importance_score",
            "timeline_json",
            "source_correlation",
            "stories",
            "first_reported_at",
            "last_reported_at",
            "metadata",
            "created_at",
            "updated_at",
        )

    def get_source_correlation(self, obj):
        return (obj.metadata or {}).get("source_correlation")


class EventIntelAssessmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventIntelAssessment
        fields = (
            "id",
            "event",
            # Diffusion
            "coverage_count",
            "distinct_source_count",
            "first_seen",
            "last_seen",
            "source_list",
            "article_links",
            "publication_timeline",
            # Cross-source comparison
            "claims",
            "agreements",
            "contradictions",
            "missing_details",
            "late_emerging_claims",
            # AI assessment
            "summary",
            "source_agreement_summary",
            "contradiction_summary",
            "dominant_narrative",
            "uncertain_elements",
            "analyst_reasoning",
            # Arabic
            "summary_ar",
            "source_agreement_summary_ar",
            "contradiction_summary_ar",
            "dominant_narrative_ar",
            "uncertain_elements_ar",
            "analyst_reasoning_ar",
            # Credibility
            "credibility_score",
            "confidence_score",
            "verification_status",
            "credibility_factors",
            # Predictions
            "escalation_probability",
            "continuation_probability",
            "hidden_link_probability",
            "monitoring_recommendation",
            "forecast_signals",
            # Meta
            "model_used",
            "status",
            "generated_at",
            "error_message",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


# ── Early Warning & Predictive Intelligence ──────────────────────────────────


class AnomalyDetectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnomalyDetection
        fields = (
            "id",
            "anomaly_type",
            "severity",
            "status",
            "title",
            "description",
            "metric_name",
            "baseline_value",
            "current_value",
            "deviation_factor",
            "confidence",
            "event",
            "entity",
            "location_country",
            "location_name",
            "evidence",
            "related_event_ids",
            "related_entity_ids",
            "detected_at",
            "expires_at",
            "created_at",
        )
        read_only_fields = fields


class SignalCorrelationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SignalCorrelation
        fields = (
            "id",
            "correlation_type",
            "strength",
            "title",
            "description",
            "correlation_score",
            "event_a",
            "event_b",
            "entity_ids",
            "anomaly_ids",
            "reasoning",
            "evidence",
            "supporting_signals",
            "detected_at",
            "created_at",
        )
        read_only_fields = fields


class PredictiveScoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = PredictiveScore
        fields = (
            "id",
            "event",
            "escalation_probability",
            "continuation_probability",
            "misleading_probability",
            "monitoring_priority",
            "anomaly_factor",
            "correlation_factor",
            "historical_factor",
            "source_diversity_factor",
            "velocity_factor",
            "reasoning",
            "reasoning_ar",
            "risk_trend",
            "weak_signals",
            "model_used",
            "scored_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class HistoricalPatternSerializer(serializers.ModelSerializer):
    matched_event_title = serializers.CharField(
        source="matched_event.title", read_only=True, default=None,
    )

    class Meta:
        model = HistoricalPattern
        fields = (
            "id",
            "event",
            "matched_event",
            "matched_event_title",
            "pattern_name",
            "similarity_score",
            "matching_dimensions",
            "historical_outcome",
            "predicted_trajectory",
            "predicted_trajectory_ar",
            "confidence",
            "created_at",
        )
        read_only_fields = fields


class GeoRadarZoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeoRadarZone
        fields = (
            "id",
            "title",
            "description",
            "center_lat",
            "center_lon",
            "radius_km",
            "location_country",
            "location_name",
            "event_count",
            "event_concentration",
            "avg_severity",
            "anomaly_count",
            "temporal_trend",
            "event_ids",
            "anomaly_ids",
            "status",
            "first_detected_at",
            "last_activity_at",
            "created_at",
        )
        read_only_fields = fields


# ═══════════════════════════════════════════════════════════════
#  SELF-LEARNING INTELLIGENCE LAYER
# ═══════════════════════════════════════════════════════════════


class AnalystFeedbackCreateSerializer(serializers.Serializer):
    """Write serializer for submitting feedback."""

    target_type = serializers.ChoiceField(choices=AnalystFeedback.TargetType.choices)
    target_id = serializers.IntegerField(min_value=1)
    feedback_type = serializers.ChoiceField(choices=AnalystFeedback.FeedbackType.choices)
    comment = serializers.CharField(required=False, allow_blank=True, default="")
    confidence = serializers.DecimalField(
        max_digits=4, decimal_places=2, required=False, default=1.00,
    )


class AnalystFeedbackSerializer(serializers.ModelSerializer):
    analyst_name = serializers.CharField(source="analyst.username", read_only=True, default="")

    class Meta:
        model = AnalystFeedback
        fields = (
            "id",
            "target_type",
            "target_id",
            "feedback_type",
            "comment",
            "analyst_name",
            "confidence",
            "context_snapshot",
            "created_at",
        )
        read_only_fields = fields


class OutcomeResolveSerializer(serializers.Serializer):
    """Write serializer for resolving an outcome."""

    target_type = serializers.ChoiceField(choices=AnalystFeedback.TargetType.choices)
    target_id = serializers.IntegerField(min_value=1)
    actual_outcome = serializers.CharField()
    accuracy_status = serializers.ChoiceField(choices=OutcomeRecord.AccuracyStatus.choices)
    resolution_notes = serializers.CharField(required=False, allow_blank=True, default="")


class OutcomeRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = OutcomeRecord
        fields = (
            "id",
            "target_type",
            "target_id",
            "expected_outcome",
            "actual_outcome",
            "accuracy_status",
            "resolved_at",
            "resolution_notes",
            "prediction_snapshot",
            "outcome_snapshot",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class SourceReputationLogSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source="source.name", read_only=True)

    class Meta:
        model = SourceReputationLog
        fields = (
            "id",
            "source",
            "source_name",
            "previous_trust",
            "new_trust",
            "change_delta",
            "reason",
            "evidence",
            "is_rollback",
            "rolled_back_at",
            "created_at",
        )
        read_only_fields = fields


class AdaptiveThresholdSerializer(serializers.ModelSerializer):
    class Meta:
        model = AdaptiveThreshold
        fields = (
            "id",
            "param_name",
            "param_type",
            "current_value",
            "previous_value",
            "default_value",
            "min_value",
            "max_value",
            "adjustment_reason",
            "version",
            "is_active",
            "updated_at",
        )
        read_only_fields = fields


class LearningRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = LearningRecord
        fields = (
            "id",
            "event",
            "record_type",
            "features",
            "prediction_scores",
            "anomaly_metrics",
            "feedback_summary",
            "outcome",
            "accuracy_label",
            "created_at",
        )
        read_only_fields = fields
