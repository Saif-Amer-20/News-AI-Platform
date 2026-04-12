from __future__ import annotations

from django.contrib import admin

from core.admin import ActorStampedAdminMixin

from .models import Alert, AlertEvent


class AlertEventInline(admin.TabularInline):
    model = AlertEvent
    extra = 0
    fields = ("event_type", "actor", "message", "created_at")
    readonly_fields = ("created_at",)
    show_change_link = True


@admin.register(Alert)
class AlertAdmin(ActorStampedAdminMixin, admin.ModelAdmin):
    list_display = ("title", "alert_type", "severity", "status", "topic", "source", "triggered_at")
    list_filter = ("alert_type", "severity", "status", "topic", "source")
    search_fields = ("title", "summary", "rationale", "dedup_key")
    autocomplete_fields = ("topic", "source", "created_by", "acknowledged_by", "resolved_by")
    inlines = (AlertEventInline,)


@admin.register(AlertEvent)
class AlertEventAdmin(admin.ModelAdmin):
    list_display = ("alert", "event_type", "actor", "created_at")
    list_filter = ("event_type", "created_at")
    search_fields = ("alert__title", "message")
    autocomplete_fields = ("alert", "actor")

