"""DRF serializers for the Cases domain (investigation workspace)."""
from __future__ import annotations

from rest_framework import serializers

from .models import (
    Case,
    CaseArticle,
    CaseEntity,
    CaseEvent,
    CaseMember,
    CaseNote,
    CaseReference,
    SavedSearch,
)


# ── Case ──────────────────────────────────────────────────────────────────────


class CaseMemberSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = CaseMember
        fields = ("id", "user", "username", "role", "created_at")
        read_only_fields = ("id", "created_at")


class CaseNoteSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.get_full_name", read_only=True, default="")

    class Meta:
        model = CaseNote
        fields = (
            "id", "note_type", "body", "is_pinned",
            "author", "author_name", "created_at", "updated_at",
        )
        read_only_fields = ("id", "author", "created_at", "updated_at")


class CaseReferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = CaseReference
        fields = (
            "id", "reference_type", "title",
            "target_app_label", "target_model", "target_object_id",
            "external_url", "metadata", "created_at",
        )
        read_only_fields = ("id", "created_at")


class CaseArticleSerializer(serializers.ModelSerializer):
    article_title = serializers.CharField(source="article.title", read_only=True)
    article_url = serializers.CharField(source="article.url", read_only=True)
    source_name = serializers.CharField(source="article.source.name", read_only=True, default="")

    class Meta:
        model = CaseArticle
        fields = (
            "id", "article", "article_title", "article_url", "source_name",
            "notes", "relevance", "created_at",
        )
        read_only_fields = ("id", "created_at")


class CaseEntitySerializer(serializers.ModelSerializer):
    entity_name = serializers.CharField(source="entity.name", read_only=True)
    entity_type = serializers.CharField(source="entity.entity_type", read_only=True)

    class Meta:
        model = CaseEntity
        fields = ("id", "entity", "entity_name", "entity_type", "notes", "created_at")
        read_only_fields = ("id", "created_at")


class CaseEventSerializer(serializers.ModelSerializer):
    event_title = serializers.CharField(source="event.title", read_only=True)
    event_type = serializers.CharField(source="event.event_type", read_only=True)

    class Meta:
        model = CaseEvent
        fields = ("id", "event", "event_title", "event_type", "notes", "created_at")
        read_only_fields = ("id", "created_at")


class CaseListSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source="owner.get_full_name", read_only=True, default="")
    article_count = serializers.IntegerField(read_only=True, default=0)
    member_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Case
        fields = (
            "id", "title", "slug", "status", "priority", "classification",
            "owner", "owner_name", "opened_at", "due_at",
            "article_count", "member_count", "created_at", "updated_at",
        )


class CaseDetailSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source="owner.get_full_name", read_only=True, default="")
    members = CaseMemberSerializer(many=True, read_only=True)
    notes = CaseNoteSerializer(many=True, read_only=True)
    references = CaseReferenceSerializer(many=True, read_only=True)
    case_articles = CaseArticleSerializer(source="articles", many=True, read_only=True)
    case_entities = CaseEntitySerializer(source="entities", many=True, read_only=True)
    case_events = CaseEventSerializer(source="events", many=True, read_only=True)

    class Meta:
        model = Case
        fields = (
            "id", "title", "slug", "description",
            "status", "priority", "classification",
            "owner", "owner_name",
            "opened_at", "closed_at", "due_at",
            "members", "notes", "references",
            "case_articles", "case_entities", "case_events",
            "metadata", "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "slug", "created_at", "updated_at",
            "members", "notes", "references",
            "case_articles", "case_entities", "case_events",
        )


class CaseCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Case
        fields = (
            "title", "description", "priority", "classification", "due_at", "metadata",
        )


# ── Saved Search ──────────────────────────────────────────────────────────────


class SavedSearchSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source="owner.get_full_name", read_only=True, default="")

    class Meta:
        model = SavedSearch
        fields = (
            "id", "name", "description", "search_type",
            "query_params", "is_global", "is_pinned",
            "last_executed_at", "execution_count",
            "owner", "owner_name", "case",
            "created_at", "updated_at",
        )
        read_only_fields = (
            "id", "owner", "last_executed_at", "execution_count",
            "created_at", "updated_at",
        )
