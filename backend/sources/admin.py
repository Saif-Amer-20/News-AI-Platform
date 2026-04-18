from __future__ import annotations

from django.contrib import admin, messages
from django.utils.html import format_html
from django.utils import timezone

from core.admin import ActorStampedAdminMixin

from .models import (
    AdaptiveThreshold,
    AnalystFeedback,
    Article,
    ArticleEntity,
    ArticleTranslation,
    Entity,
    EntityInfluenceScore,
    EntityMergeAudit,
    EntityRelationship,
    EntityReviewQueue,
    EntitySignal,
    Event,
    EventIntelAssessment,
    LearningRecord,
    OutcomeRecord,
    ParsedArticleCandidate,
    RawItem,
    Source,
    SourceFetchError,
    SourceFetchRun,
    SourceHealthEvent,
    SourceReputationLog,
    Story,
)


# ═══════════════════════════════════════════════════════════════
#  Helper formatters
# ═══════════════════════════════════════════════════════════════

def _health_badge(status: str) -> str:
    colors = {
        "healthy": "#16a34a",
        "degraded": "#d97706",
        "failing": "#dc2626",
        "unknown": "#94a3b8",
    }
    bg = colors.get(status, "#94a3b8")
    return format_html(
        '<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
        'font-size:0.75rem;font-weight:600;color:#fff;background:{bg};">{label}</span>',
        bg=bg,
        label=status.capitalize(),
    )


def _status_pill(status: str) -> str:
    colors = {
        "running": "#2563eb",
        "completed": "#16a34a",
        "partial": "#d97706",
        "failed": "#dc2626",
        "fetched": "#2563eb",
        "parsed": "#7c3aed",
        "normalized": "#059669",
        "article_created": "#16a34a",
        "pending": "#94a3b8",
    }
    bg = colors.get(status, "#64748b")
    return format_html(
        '<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
        'font-size:0.72rem;font-weight:600;color:#fff;background:{bg};">{label}</span>',
        bg=bg,
        label=status.replace("_", " ").capitalize(),
    )


# ═══════════════════════════════════════════════════════════════
#  Inlines
# ═══════════════════════════════════════════════════════════════

class SourceHealthEventInline(admin.TabularInline):
    model = SourceHealthEvent
    extra = 0
    fields = ("health_status", "status_code", "response_time_ms", "detail", "created_at")
    readonly_fields = ("created_at",)
    show_change_link = True
    max_num = 10
    verbose_name = "Recent Health Check"
    verbose_name_plural = "Recent Health Checks (last 10)"

    def get_queryset(self, request):
        return super().get_queryset(request).order_by("-created_at")


class SourceFetchRunInline(admin.TabularInline):
    model = SourceFetchRun
    extra = 0
    fields = ("started_at", "finished_at", "status", "items_fetched", "items_created")
    readonly_fields = ("started_at", "finished_at", "items_fetched", "items_created")
    show_change_link = True
    max_num = 10
    verbose_name = "Recent Fetch Run"
    verbose_name_plural = "Recent Fetch Runs (last 10)"

    def get_queryset(self, request):
        return super().get_queryset(request).order_by("-started_at")


class ArticleEntityInline(admin.TabularInline):
    model = ArticleEntity
    extra = 0
    fields = ("entity", "relevance_score", "mention_count", "context_snippet")
    readonly_fields = ("relevance_score", "mention_count")
    autocomplete_fields = ("entity",)


class StoryInline(admin.TabularInline):
    model = Story
    extra = 0
    fields = ("title", "article_count", "importance_score", "first_published_at")
    readonly_fields = ("title", "article_count", "importance_score", "first_published_at")
    show_change_link = True


# ═══════════════════════════════════════════════════════════════
#  1. SOURCE MANAGEMENT — The primary operator interface
# ═══════════════════════════════════════════════════════════════

@admin.register(Source)
class SourceAdmin(ActorStampedAdminMixin, admin.ModelAdmin):
    # ── List page ──────────────────────────────────────────
    list_display = (
        "name",
        "source_type",
        "is_active_icon",
        "language",
        "country",
        "trust_score",
        "fetch_interval_display",
        "health_badge",
        "last_success_display",
        "last_error_display",
        "total_articles_fetched",
    )
    list_display_links = ("name",)
    list_filter = (
        "is_active",
        "health_status",
        "status",
        "source_type",
        "parser_type",
        "language",
        "country",
    )
    search_fields = ("name", "description", "base_url", "endpoint_url", "slug")
    list_per_page = 25
    list_editable = ("trust_score",)
    ordering = ("name",)

    # ── Detail form ────────────────────────────────────────
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("created_by", "updated_by")

    fieldsets = (
        ("Source Identity", {
            "fields": ("name", "slug", "description"),
            "description": "Basic information about this source. The slug is auto-generated.",
        }),
        ("Connection", {
            "fields": ("source_type", "parser_type", "base_url", "endpoint_url", "parser_config"),
            "description": "How the system fetches data from this source.",
        }),
        ("Locale & Trust", {
            "fields": ("language", "country", "default_language", "default_country", "trust_score", "is_public"),
        }),
        ("Fetch Schedule", {
            "fields": ("is_active", "status", "fetch_interval_minutes", "polling_interval_minutes", "request_timeout_seconds"),
            "description": "Controls how often the ingestion pipeline polls this source.",
        }),
        ("Operational Status (read-only)", {
            "fields": (
                "health_status", "last_checked_at", "last_success_at",
                "last_failure_at", "last_error_message",
            ),
            "classes": ("collapse",),
            "description": "These fields are updated automatically by the fetch pipeline. Do not edit manually.",
        }),
        ("Quality Metrics (read-only)", {
            "fields": ("total_articles_fetched", "total_duplicates", "total_low_quality", "avg_quality_score"),
            "classes": ("collapse",),
        }),
        ("Audit", {
            "fields": ("created_by", "updated_by"),
            "classes": ("collapse",),
        }),
    )

    readonly_fields = (
        "health_status",
        "last_checked_at",
        "last_success_at",
        "last_failure_at",
        "last_error_message",
        "total_articles_fetched",
        "total_duplicates",
        "total_low_quality",
        "avg_quality_score",
    )

    inlines = (SourceFetchRunInline, SourceHealthEventInline)

    # ── Custom column renderers ────────────────────────────
    @admin.display(description="Active", boolean=True, ordering="is_active")
    def is_active_icon(self, obj):
        return obj.is_active

    @admin.display(description="Health", ordering="health_status")
    def health_badge(self, obj):
        return _health_badge(obj.health_status)

    @admin.display(description="Fetch Interval", ordering="fetch_interval_minutes")
    def fetch_interval_display(self, obj):
        mins = obj.effective_fetch_interval()
        if mins >= 60:
            return f"{mins // 60}h {mins % 60}m" if mins % 60 else f"{mins // 60}h"
        return f"{mins}m"

    @admin.display(description="Last Success", ordering="last_success_at")
    def last_success_display(self, obj):
        if not obj.last_success_at:
            return format_html('<span style="color:#94a3b8;">Never</span>')
        return obj.last_success_at.strftime("%Y-%m-%d %H:%M")

    @admin.display(description="Last Error", ordering="last_failure_at")
    def last_error_display(self, obj):
        if not obj.last_failure_at:
            return format_html('<span style="color:#16a34a;">None</span>')
        short = (obj.last_error_message or "")[:60]
        return format_html(
            '<span title="{full}" style="color:#dc2626;font-size:0.75rem;">{short}…</span>',
            full=obj.last_error_message or "",
            short=short,
        )

    # ── Admin Actions ──────────────────────────────────────
    actions = ["activate_sources", "deactivate_sources", "mark_healthy"]

    @admin.action(description="✅ Activate selected sources")
    def activate_sources(self, request, queryset):
        count = queryset.update(is_active=True, status=Source.Status.ACTIVE)
        self.message_user(request, f"Activated {count} source(s).", messages.SUCCESS)

    @admin.action(description="⏸ Deactivate selected sources")
    def deactivate_sources(self, request, queryset):
        count = queryset.update(is_active=False, status=Source.Status.PAUSED)
        self.message_user(request, f"Deactivated {count} source(s).", messages.WARNING)

    @admin.action(description="🔄 Reset health to Unknown")
    def mark_healthy(self, request, queryset):
        count = queryset.update(
            health_status=Source.HealthStatus.UNKNOWN,
            last_error_message="",
        )
        self.message_user(request, f"Reset health for {count} source(s).", messages.SUCCESS)


# ═══════════════════════════════════════════════════════════════
#  2. INGESTION PIPELINE — Operator monitoring
# ═══════════════════════════════════════════════════════════════

@admin.register(SourceHealthEvent)
class SourceHealthEventAdmin(admin.ModelAdmin):
    list_display = ("source", "health_badge", "status_code", "response_time_ms", "detail_short", "created_at")
    list_filter = ("health_status", "source")
    search_fields = ("source__name", "detail")
    autocomplete_fields = ("source",)
    list_per_page = 50
    readonly_fields = ("source", "health_status", "status_code", "response_time_ms", "detail", "payload", "created_at")

    @admin.display(description="Health")
    def health_badge(self, obj):
        return _health_badge(obj.health_status)

    @admin.display(description="Detail")
    def detail_short(self, obj):
        return (obj.detail or "")[:80] or "—"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SourceFetchRun)
class SourceFetchRunAdmin(admin.ModelAdmin):
    list_display = (
        "source",
        "status_badge",
        "started_at",
        "finished_at",
        "duration_display",
        "items_fetched",
        "items_created",
    )
    list_filter = ("status", "source", "started_at")
    search_fields = ("source__name",)
    autocomplete_fields = ("source",)
    list_per_page = 50
    readonly_fields = ("source", "started_at", "finished_at", "status", "items_fetched", "items_created", "detail")
    date_hierarchy = "started_at"

    @admin.display(description="Status")
    def status_badge(self, obj):
        return _status_pill(obj.status)

    @admin.display(description="Duration")
    def duration_display(self, obj):
        if not obj.finished_at or not obj.started_at:
            if obj.status == "running":
                return format_html('<span style="color:#2563eb;">Running…</span>')
            return "—"
        delta = obj.finished_at - obj.started_at
        secs = int(delta.total_seconds())
        if secs < 60:
            return f"{secs}s"
        return f"{secs // 60}m {secs % 60}s"

    def has_add_permission(self, request):
        return False


@admin.register(SourceFetchError)
class SourceFetchErrorAdmin(admin.ModelAdmin):
    list_display = ("source", "error_short", "url_short", "fetch_run", "timestamp")
    list_filter = ("source", "timestamp")
    search_fields = ("source__name", "url", "error")
    autocomplete_fields = ("source", "fetch_run")
    list_per_page = 50
    readonly_fields = ("source", "fetch_run", "url", "error", "timestamp")
    date_hierarchy = "timestamp"

    @admin.display(description="Error")
    def error_short(self, obj):
        short = (obj.error or "")[:80]
        return format_html(
            '<span title="{full}" style="color:#dc2626;">{short}</span>',
            full=obj.error or "",
            short=short,
        )

    @admin.display(description="URL")
    def url_short(self, obj):
        if not obj.url:
            return "—"
        short = obj.url[:50]
        return format_html('<a href="{url}" target="_blank" rel="noopener">{short}…</a>', url=obj.url, short=short)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(RawItem)
class RawItemAdmin(admin.ModelAdmin):
    list_display = ("title_short", "source", "status_badge", "fetched_at", "url_short")
    list_filter = ("status", "source", "fetched_at")
    search_fields = ("url", "title_raw", "content_hash")
    autocomplete_fields = ("source", "fetch_run")
    list_per_page = 50
    date_hierarchy = "fetched_at"

    fieldsets = (
        (None, {
            "fields": ("source", "fetch_run", "url", "status", "fetched_at"),
        }),
        ("Content", {
            "fields": ("title_raw", "content_raw", "html_raw"),
            "classes": ("collapse",),
        }),
        ("Meta", {
            "fields": ("content_hash", "raw_storage_key", "error_message", "metadata"),
            "classes": ("collapse",),
        }),
    )
    readonly_fields = ("source", "fetch_run", "url", "fetched_at", "content_hash", "raw_storage_key")

    @admin.display(description="Status")
    def status_badge(self, obj):
        return _status_pill(obj.status)

    @admin.display(description="Title", ordering="title_raw")
    def title_short(self, obj):
        return (obj.title_raw or "—")[:60]

    @admin.display(description="URL")
    def url_short(self, obj):
        if not obj.url:
            return "—"
        short = obj.url[:50]
        return format_html('<a href="{url}" target="_blank" rel="noopener">{short}…</a>', url=obj.url, short=short)

    def has_add_permission(self, request):
        return False


@admin.register(ParsedArticleCandidate)
class ParsedArticleCandidateAdmin(admin.ModelAdmin):
    list_display = ("title_short", "source_name", "status_badge", "author", "published_at", "updated_at")
    list_filter = ("status", "published_at")
    search_fields = ("title", "content", "author")
    autocomplete_fields = ("raw_item",)
    list_per_page = 50

    fieldsets = (
        (None, {
            "fields": ("raw_item", "title", "status", "published_at", "author", "image_url"),
        }),
        ("Content", {
            "fields": ("content",),
            "classes": ("collapse",),
        }),
        ("Meta", {
            "fields": ("error_message", "metadata"),
            "classes": ("collapse",),
        }),
    )
    readonly_fields = ("raw_item",)

    @admin.display(description="Status")
    def status_badge(self, obj):
        return _status_pill(obj.status)

    @admin.display(description="Title", ordering="title")
    def title_short(self, obj):
        return (obj.title or "—")[:60]

    @admin.display(description="Source")
    def source_name(self, obj):
        return obj.raw_item.source.name if obj.raw_item_id else "—"

    def has_add_permission(self, request):
        return False


# ═══════════════════════════════════════════════════════════════
#  3. INTELLIGENCE OBJECTS — Generated models (mostly read-only)
# ═══════════════════════════════════════════════════════════════

@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = (
        "title_short",
        "source",
        "published_at",
        "is_duplicate",
        "quality_score",
        "importance_score",
        "story",
    )
    list_filter = ("source", "is_duplicate", "published_at")
    search_fields = ("title", "normalized_title", "url", "canonical_url", "content_hash")
    autocomplete_fields = ("source", "raw_item", "parsed_candidate", "story", "duplicate_of")
    list_per_page = 50
    date_hierarchy = "published_at"

    fieldsets = (
        (None, {
            "fields": ("title", "url", "canonical_url", "source", "published_at", "author", "image_url"),
            "description": (
                "⚠️ Articles are generated automatically by the ingestion pipeline. "
                "Do not create articles manually."
            ),
        }),
        ("Pipeline Links", {
            "fields": ("raw_item", "parsed_candidate", "story", "duplicate_of", "is_duplicate"),
        }),
        ("Scores (read-only)", {
            "fields": ("quality_score", "importance_score"),
        }),
        ("Content", {
            "fields": ("normalized_title", "content", "normalized_content"),
            "classes": ("collapse",),
        }),
        ("Meta", {
            "fields": ("content_hash", "matched_rule_labels", "metadata"),
            "classes": ("collapse",),
        }),
    )
    readonly_fields = ("quality_score", "importance_score", "content_hash")

    @admin.display(description="Title", ordering="title")
    def title_short(self, obj):
        return (obj.title or "—")[:70]


@admin.register(Story)
class StoryAdmin(admin.ModelAdmin):
    list_display = (
        "title_short",
        "story_key",
        "article_count",
        "importance_score",
        "event",
        "first_published_at",
        "last_published_at",
    )
    list_filter = ("event__event_type",)
    search_fields = ("title", "story_key")
    autocomplete_fields = ("event",)
    readonly_fields = ("importance_score", "article_count", "story_key")
    list_per_page = 50

    @admin.display(description="Title", ordering="title")
    def title_short(self, obj):
        return (obj.title or "—")[:70]

    def has_add_permission(self, request):
        return False

    class Media:
        pass  # placeholder for potential future JS


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        "title_short",
        "event_type",
        "location_name",
        "location_country",
        "story_count",
        "source_count",
        "confidence_score",
        "conflict_flag",
        "importance_score",
        "first_reported_at",
    )
    list_filter = ("event_type", "location_country", "conflict_flag")
    search_fields = ("title", "description", "location_name")
    list_per_page = 50

    fieldsets = (
        (None, {
            "fields": ("title", "slug", "description", "event_type"),
            "description": (
                "⚠️ Events are generated automatically by the clustering pipeline. "
                "Manual creation is not recommended."
            ),
        }),
        ("Location", {
            "fields": ("location_name", "location_country", "location_lat", "location_lon", "geo_confidence"),
        }),
        ("Scores (read-only)", {
            "fields": (
                "story_count", "source_count", "importance_score",
                "confidence_score", "conflict_flag",
            ),
        }),
        ("Timeline", {
            "fields": ("first_reported_at", "last_reported_at", "timeline_json"),
            "classes": ("collapse",),
        }),
        ("Meta", {
            "fields": ("metadata",),
            "classes": ("collapse",),
        }),
    )
    readonly_fields = (
        "story_count", "source_count", "importance_score",
        "confidence_score", "geo_confidence", "conflict_flag",
        "timeline_json", "first_reported_at", "last_reported_at",
    )
    inlines = (StoryInline,)

    @admin.display(description="Title", ordering="title")
    def title_short(self, obj):
        return (obj.title or "—")[:70]

    def has_add_permission(self, request):
        return False


@admin.register(Entity)
class EntityAdmin(admin.ModelAdmin):
    list_display = ("name", "entity_type", "normalized_name", "canonical_name", "country")
    list_filter = ("entity_type", "country")
    search_fields = ("name", "normalized_name", "canonical_name")
    readonly_fields = ("canonical_name", "aliases")
    list_per_page = 50

    def has_add_permission(self, request):
        return False


@admin.register(ArticleEntity)
class ArticleEntityAdmin(admin.ModelAdmin):
    list_display = ("article", "entity", "relevance_score", "mention_count")
    list_filter = ("entity__entity_type",)
    search_fields = ("entity__name", "article__title")
    autocomplete_fields = ("article", "entity")
    list_per_page = 50

    def has_add_permission(self, request):
        return False


@admin.register(ArticleTranslation)
class ArticleTranslationAdmin(admin.ModelAdmin):
    list_display = ("article", "language_code", "translation_status", "provider", "translated_at")
    list_filter = ("language_code", "translation_status", "provider")
    search_fields = ("article__title", "translated_title")
    autocomplete_fields = ("article",)
    list_per_page = 50
    readonly_fields = (
        "article", "language_code", "translated_title", "translated_body",
        "translation_status", "translated_at", "provider", "error_message",
    )

    def has_add_permission(self, request):
        return False


@admin.register(EventIntelAssessment)
class EventIntelAssessmentAdmin(admin.ModelAdmin):
    list_display = ("event", "status", "credibility_score", "verification_status", "generated_at")
    list_filter = ("status", "verification_status")
    search_fields = ("event__title",)
    autocomplete_fields = ("event",)
    list_per_page = 50
    readonly_fields = (
        "event", "coverage_count", "distinct_source_count", "first_seen", "last_seen",
        "credibility_score", "confidence_score", "verification_status",
        "escalation_probability", "continuation_probability", "hidden_link_probability",
        "model_used", "status", "generated_at", "error_message",
    )

    def has_add_permission(self, request):
        return False


# ═══════════════════════════════════════════════════════════════
#  Self-Learning Intelligence Layer
# ═══════════════════════════════════════════════════════════════


@admin.register(AnalystFeedback)
class AnalystFeedbackAdmin(admin.ModelAdmin):
    list_display = ("id", "target_type", "target_id", "feedback_type", "analyst", "created_at")
    list_filter = ("target_type", "feedback_type")
    search_fields = ("comment",)
    list_per_page = 50
    readonly_fields = ("context_snapshot",)


@admin.register(OutcomeRecord)
class OutcomeRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "target_type", "target_id", "accuracy_status", "resolved_at", "created_at")
    list_filter = ("accuracy_status", "target_type")
    list_per_page = 50
    readonly_fields = ("prediction_snapshot", "outcome_snapshot")


@admin.register(SourceReputationLog)
class SourceReputationLogAdmin(admin.ModelAdmin):
    list_display = ("id", "source", "previous_trust", "new_trust", "change_delta", "reason", "created_at")
    list_filter = ("reason", "is_rollback")
    search_fields = ("source__name",)
    autocomplete_fields = ("source",)
    list_per_page = 50
    readonly_fields = ("evidence",)


@admin.register(AdaptiveThreshold)
class AdaptiveThresholdAdmin(admin.ModelAdmin):
    list_display = ("param_name", "param_type", "current_value", "default_value", "version", "is_active")
    list_filter = ("param_type", "is_active")
    search_fields = ("param_name",)
    list_per_page = 50
    readonly_fields = ("evidence",)


@admin.register(LearningRecord)
class LearningRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "record_type", "accuracy_label", "event", "created_at")
    list_filter = ("record_type", "accuracy_label")
    autocomplete_fields = ("event",)
    list_per_page = 50
    readonly_fields = ("features", "prediction_scores", "anomaly_metrics", "feedback_summary", "outcome")


# ═══════════════════════════════════════════════════════════════
#  AI-Driven Entity Consolidation
# ═══════════════════════════════════════════════════════════════

def _confidence_badge(score) -> str:
    """Render a colour-coded confidence badge."""
    val = float(score)
    if val >= 0.92:
        bg = "#16a34a"  # green — auto-merge range
    elif val >= 0.72:
        bg = "#d97706"  # amber — review range
    else:
        bg = "#94a3b8"  # grey — keep separate
    return format_html(
        '<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
        'font-size:0.75rem;font-weight:600;color:#fff;background:{bg};">{val:.3f}</span>',
        bg=bg,
        val=val,
    )


@admin.register(EntityReviewQueue)
class EntityReviewQueueAdmin(admin.ModelAdmin):
    """Review queue for ambiguous entity merge candidates."""

    list_display = (
        "candidate_name", "arrow", "matched_name",
        "entity_type_display", "confidence_badge",
        "merge_method", "status", "created_at",
    )
    list_filter = ("status", "merge_method", "candidate_entity__entity_type")
    search_fields = (
        "candidate_entity__name", "matched_entity__name", "explanation",
    )
    readonly_fields = (
        "candidate_entity", "matched_entity",
        "similarity_score", "context_score", "final_score",
        "merge_method", "explanation", "supporting_article_ids",
        "reviewed_by", "reviewed_at", "review_note",
        "created_at", "updated_at",
    )
    list_per_page = 50
    ordering = ("-final_score", "-created_at")
    actions = ["approve_merge", "reject_merge"]

    # ── Display helpers ─────────────────────────────────────────────────────

    @admin.display(description="Candidate")
    def candidate_name(self, obj):
        return obj.candidate_entity.name

    @admin.display(description="→")
    def arrow(self, obj):
        return format_html('<span style="color:#94a3b8">→</span>')

    @admin.display(description="Matched Canonical")
    def matched_name(self, obj):
        return obj.matched_entity.name

    @admin.display(description="Type")
    def entity_type_display(self, obj):
        return obj.candidate_entity.get_entity_type_display()

    @admin.display(description="Score")
    def confidence_badge(self, obj):
        return _confidence_badge(obj.final_score)
    confidence_badge.allow_tags = True

    # ── Actions ─────────────────────────────────────────────────────────────

    @admin.action(description="✅ Approve & execute merge")
    def approve_merge(self, request, queryset):
        from services.orchestration.entity_consolidation_service import EntityConsolidationService

        service = EntityConsolidationService()
        approved = 0
        skipped = 0
        for item in queryset.filter(status=EntityReviewQueue.Status.PENDING):
            if service.process_review_queue_approval(item.pk, request.user):
                approved += 1
            else:
                skipped += 1
        self.message_user(
            request,
            f"{approved} merge(s) approved and executed; {skipped} skipped.",
            messages.SUCCESS if approved else messages.WARNING,
        )

    @admin.action(description="❌ Reject merge (keep entities separate)")
    def reject_merge(self, request, queryset):
        from services.orchestration.entity_consolidation_service import EntityConsolidationService

        service = EntityConsolidationService()
        rejected = 0
        for item in queryset.filter(status=EntityReviewQueue.Status.PENDING):
            service.process_review_queue_rejection(item.pk, request.user, note="Bulk rejection")
            rejected += 1
        self.message_user(
            request,
            f"{rejected} merge proposal(s) rejected.",
            messages.SUCCESS,
        )

    def has_add_permission(self, request):
        return False


@admin.register(EntityMergeAudit)
class EntityMergeAuditAdmin(admin.ModelAdmin):
    """Read-only audit trail for all AI-executed entity merges."""

    list_display = (
        "source_entity_name", "arrow", "target_entity_name",
        "source_entity_type", "confidence_badge",
        "merge_method", "rolled_back_badge", "created_at",
    )
    list_filter = ("merge_method", "source_entity_type", "rolled_back")
    search_fields = ("source_entity_name", "target_entity_name", "merge_reason")
    readonly_fields = (
        "source_entity_id", "source_entity_name", "source_entity_type",
        "source_entity_canonical", "source_article_count", "source_aliases",
        "target_entity", "target_entity_name",
        "confidence", "merge_method", "merge_reason", "article_evidence",
        "rolled_back", "rolled_back_at", "rolled_back_by", "rollback_note",
        "created_at", "updated_at",
    )
    list_per_page = 50
    ordering = ("-created_at",)
    actions = ["rollback_merge_action"]

    # ── Display helpers ─────────────────────────────────────────────────────

    @admin.display(description="→")
    def arrow(self, obj):
        return format_html('<span style="color:#94a3b8">→</span>')

    @admin.display(description="Confidence")
    def confidence_badge(self, obj):
        return _confidence_badge(obj.confidence)
    confidence_badge.allow_tags = True

    @admin.display(description="Status")
    def rolled_back_badge(self, obj):
        if obj.rolled_back:
            return format_html(
                '<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
                'font-size:0.75rem;font-weight:600;color:#fff;background:#dc2626;">ROLLED BACK</span>'
            )
        return format_html(
            '<span style="display:inline-block;padding:2px 8px;border-radius:4px;'
            'font-size:0.75rem;font-weight:600;color:#fff;background:#16a34a;">Active</span>'
        )
    rolled_back_badge.allow_tags = True

    # ── Actions ─────────────────────────────────────────────────────────────

    @admin.action(description="↩ Roll back selected merges")
    def rollback_merge_action(self, request, queryset):
        from services.orchestration.entity_consolidation_service import EntityConsolidationService

        service = EntityConsolidationService()
        rolled_back = 0
        skipped = 0
        for audit in queryset.filter(rolled_back=False):
            if service.rollback_merge(audit.pk, request.user, note="Admin rollback"):
                rolled_back += 1
            else:
                skipped += 1
        self.message_user(
            request,
            f"{rolled_back} merge(s) rolled back; {skipped} skipped (already rolled back or target deleted).",
            messages.SUCCESS if rolled_back else messages.WARNING,
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False  # audit records are immutable


# ═══════════════════════════════════════════════════════════════
#  Entity Intelligence Layer Admin
# ═══════════════════════════════════════════════════════════════


@admin.register(EntityRelationship)
class EntityRelationshipAdmin(admin.ModelAdmin):
    """View and browse stored entity co-occurrence relationships."""

    list_display = (
        "entity_a", "entity_b", "relationship_type_badge",
        "strength_score", "confidence", "co_occurrence_count",
        "source_diversity_score", "last_seen_at",
    )
    list_filter = ("relationship_type",)
    search_fields = (
        "entity_a__name", "entity_a__canonical_name",
        "entity_b__name", "entity_b__canonical_name",
    )
    readonly_fields = (
        "entity_a", "entity_b",
        "strength_score", "confidence", "recency_score", "source_diversity_score",
        "co_occurrence_count", "growth_rate", "prev_co_occurrence_count",
        "relationship_type",
        "first_seen_at", "last_seen_at",
        "supporting_article_ids", "supporting_source_ids",
        "created_at", "updated_at",
    )
    ordering = ("-strength_score",)
    list_per_page = 50

    @admin.display(description="Type")
    def relationship_type_badge(self, obj):
        colors = {
            "political":  "#3b82f6",
            "military":   "#ef4444",
            "economic":   "#10b981",
            "diplomatic": "#8b5cf6",
            "conflict":   "#f97316",
            "social":     "#06b6d4",
            "unknown":    "#94a3b8",
        }
        bg = colors.get(obj.relationship_type, "#94a3b8")
        return format_html(
            '<span style="display:inline-block;padding:2px 7px;border-radius:4px;'
            'font-size:0.72rem;font-weight:600;color:#fff;background:{bg};">{label}</span>',
            bg=bg,
            label=obj.get_relationship_type_display(),
        )

    def has_add_permission(self, request):
        return False


@admin.register(EntityInfluenceScore)
class EntityInfluenceScoreAdmin(admin.ModelAdmin):
    """Cached influence metrics per entity."""

    list_display = (
        "entity", "influence_rank", "influence_score",
        "degree_centrality", "velocity_score",
        "mentions_last_24h", "mentions_last_7d",
        "growth_flag", "scored_at",
    )
    list_filter = ("growth_flag",)
    search_fields = ("entity__name", "entity__canonical_name")
    readonly_fields = [f.name for f in EntityInfluenceScore._meta.get_fields() if hasattr(f, "name")]
    ordering = ("influence_rank",)
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(EntitySignal)
class EntitySignalAdmin(admin.ModelAdmin):
    """Entity intelligence signals feed."""

    list_display = (
        "title", "severity_badge", "signal_type", "entity",
        "related_entity", "is_read", "created_at",
    )
    list_filter = ("signal_type", "severity", "is_read")
    search_fields = ("title", "entity__name", "description")
    readonly_fields = (
        "entity", "signal_type", "severity", "title", "description",
        "metadata", "related_entity", "expires_at", "created_at", "updated_at",
    )
    ordering = ("-created_at",)
    list_per_page = 50
    actions = ["mark_read_action"]

    @admin.display(description="Severity")
    def severity_badge(self, obj):
        colors = {"high": "#dc2626", "medium": "#d97706", "low": "#16a34a"}
        bg = colors.get(obj.severity, "#94a3b8")
        return format_html(
            '<span style="display:inline-block;padding:2px 7px;border-radius:4px;'
            'font-size:0.72rem;font-weight:600;color:#fff;background:{bg};">{label}</span>',
            bg=bg,
            label=obj.get_severity_display(),
        )

    @admin.action(description="Mark selected signals as read")
    def mark_read_action(self, request, queryset):
        updated = queryset.update(is_read=True)
        self.message_user(request, f"{updated} signal(s) marked as read.", messages.SUCCESS)

    def has_add_permission(self, request):
        return False
