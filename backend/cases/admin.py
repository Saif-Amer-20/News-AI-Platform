from __future__ import annotations

from django.contrib import admin

from core.admin import ActorStampedAdminMixin

from .models import Case, CaseMember, CaseNote, CaseReference


class CaseMemberInline(admin.TabularInline):
    model = CaseMember
    extra = 0
    fields = ("user", "role", "assigned_by", "created_at")
    readonly_fields = ("created_at",)
    show_change_link = True


class CaseNoteInline(admin.TabularInline):
    model = CaseNote
    extra = 0
    fields = ("author", "note_type", "is_pinned", "created_at")
    readonly_fields = ("created_at",)
    show_change_link = True


class CaseReferenceInline(admin.TabularInline):
    model = CaseReference
    extra = 0
    fields = ("title", "reference_type", "external_url", "created_at")
    readonly_fields = ("created_at",)
    show_change_link = True


@admin.register(Case)
class CaseAdmin(ActorStampedAdminMixin, admin.ModelAdmin):
    list_display = ("title", "status", "priority", "classification", "owner", "opened_at", "closed_at")
    list_filter = ("status", "priority", "classification")
    search_fields = ("title", "description")
    prepopulated_fields = {"slug": ("title",)}
    autocomplete_fields = ("owner", "created_by", "updated_by")
    inlines = (CaseMemberInline, CaseNoteInline, CaseReferenceInline)


@admin.register(CaseMember)
class CaseMemberAdmin(admin.ModelAdmin):
    list_display = ("case", "user", "role", "assigned_by", "created_at")
    list_filter = ("role", "case")
    search_fields = ("case__title", "user__username")
    autocomplete_fields = ("case", "user", "assigned_by")


@admin.register(CaseNote)
class CaseNoteAdmin(admin.ModelAdmin):
    list_display = ("case", "author", "note_type", "is_pinned", "created_at")
    list_filter = ("note_type", "is_pinned")
    search_fields = ("case__title", "body", "author__username")
    autocomplete_fields = ("case", "author")


@admin.register(CaseReference)
class CaseReferenceAdmin(admin.ModelAdmin):
    list_display = ("case", "title", "reference_type", "target_model", "external_url", "created_at")
    list_filter = ("reference_type",)
    search_fields = ("case__title", "title", "target_model", "target_object_id", "external_url")
    autocomplete_fields = ("case", "added_by")

