from __future__ import annotations

from django.contrib import admin

from .dlq import DeadLetterItem
from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "action",
        "severity",
        "actor",
        "actor_type",
        "target_app_label",
        "target_model",
        "target_object_id",
    )
    list_filter = ("severity", "actor_type", "target_app_label", "target_model")
    search_fields = ("action", "message", "request_id", "target_object_id", "actor__username")
    autocomplete_fields = ("actor",)
    readonly_fields = (
        "created_at",
        "updated_at",
        "action",
        "actor",
        "actor_type",
        "target_app_label",
        "target_model",
        "target_object_id",
        "severity",
        "message",
        "remote_addr",
        "request_id",
        "metadata",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(DeadLetterItem)
class DeadLetterItemAdmin(admin.ModelAdmin):
    list_display = (
        "created_at", "task_name", "status", "exception_type",
        "retry_count", "resolved_at",
    )
    list_filter = ("status", "task_name")
    search_fields = ("task_name", "task_id", "exception_message")
    readonly_fields = (
        "created_at", "updated_at", "task_name", "task_id",
        "args", "kwargs", "exception_type", "exception_message",
        "traceback", "retry_count", "metadata",
    )
    actions = ["replay_selected", "discard_selected"]

    @admin.action(description="Replay selected tasks")
    def replay_selected(self, request, queryset):
        count = 0
        for item in queryset.filter(status=DeadLetterItem.Status.PENDING):
            item.replay()
            count += 1
        self.message_user(request, f"Replayed {count} task(s).")

    @admin.action(description="Discard selected tasks")
    def discard_selected(self, request, queryset):
        count = queryset.filter(status=DeadLetterItem.Status.PENDING).update(
            status=DeadLetterItem.Status.DISCARDED,
        )
        self.message_user(request, f"Discarded {count} task(s).")

