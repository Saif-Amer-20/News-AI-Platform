from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User

from .models import UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    extra = 0
    can_delete = False
    fk_name = "user"


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "default_role",
        "clearance_level",
        "team_name",
        "timezone",
        "is_on_call",
        "updated_at",
    )
    list_filter = ("default_role", "clearance_level", "is_on_call", "team_name")
    search_fields = ("user__username", "user__first_name", "user__last_name", "team_name")
    autocomplete_fields = ("user",)


admin.site.unregister(User)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    inlines = (UserProfileInline,)
