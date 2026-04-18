from django.contrib import admin

from validation.models import ValidationRun, ValidationTag


@admin.register(ValidationTag)
class ValidationTagAdmin(admin.ModelAdmin):
    list_display = ("article", "tag_type", "tagged_by", "created_at")
    list_filter = ("tag_type", "created_at")
    search_fields = ("article__title", "notes", "correct_value")
    raw_id_fields = ("article",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(ValidationRun)
class ValidationRunAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "articles_sampled", "elapsed_seconds", "created_at")
    list_filter = ("status", "created_at")
    readonly_fields = ("created_at", "updated_at", "report_json")
