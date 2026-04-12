"""DRF serializers for the Sources domain."""
from __future__ import annotations

from rest_framework import serializers

from .models import (
    Article,
    ArticleAISummary,
    ArticleEntity,
    ArticleTranslation,
    Entity,
    Event,
    RawItem,
    Source,
    SourceFetchRun,
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
