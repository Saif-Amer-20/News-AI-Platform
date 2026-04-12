from __future__ import annotations

from django.contrib import admin

from core.admin import ActorStampedAdminMixin

from .models import KeywordRule, Topic, Watchlist


class WatchlistInline(admin.TabularInline):
    model = Watchlist
    extra = 0
    fields = ("name", "watchlist_type", "status", "owner")
    show_change_link = True


@admin.register(Topic)
class TopicAdmin(ActorStampedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "status", "priority", "owner", "geography_focus", "updated_at")
    list_filter = ("status", "priority")
    search_fields = ("name", "description", "geography_focus")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("owner", "created_by", "updated_by")
    inlines = (WatchlistInline,)


@admin.register(Watchlist)
class WatchlistAdmin(ActorStampedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "topic", "watchlist_type", "status", "owner", "updated_at")
    list_filter = ("watchlist_type", "status", "topic")
    search_fields = ("name", "description", "topic__name")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("topic", "owner", "created_by", "updated_by")


@admin.register(KeywordRule)
class KeywordRuleAdmin(ActorStampedAdminMixin, admin.ModelAdmin):
    list_display = (
        "label",
        "topic",
        "watchlist",
        "rule_type",
        "match_target",
        "priority",
        "enabled",
        "is_exclusion",
    )
    list_filter = ("topic", "rule_type", "match_target", "priority", "enabled", "is_exclusion")
    search_fields = ("label", "pattern", "topic__name", "watchlist__name")
    autocomplete_fields = ("topic", "watchlist", "created_by", "updated_by")

