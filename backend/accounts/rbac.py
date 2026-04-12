from __future__ import annotations

from collections.abc import Iterable

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import transaction
from django.db.models import Q

from .models import UserProfile

User = get_user_model()

CUSTOM_APP_LABELS = ("accounts", "topics", "sources", "alerts", "cases", "ops")
PLATFORM_ADMIN_AUTH_CODENAMES = (
    "add_user",
    "change_user",
    "delete_user",
    "view_user",
    "add_group",
    "change_group",
    "delete_group",
    "view_group",
)

DEFAULT_GROUP_PERMISSIONS: dict[str, tuple[str, ...] | None] = {
    "intel_analyst": (
        "accounts.view_userprofile",
        "topics.add_topic",
        "topics.change_topic",
        "topics.view_topic",
        "topics.add_watchlist",
        "topics.change_watchlist",
        "topics.view_watchlist",
        "topics.add_keywordrule",
        "topics.change_keywordrule",
        "topics.view_keywordrule",
        "sources.view_source",
        "sources.view_sourcehealthevent",
        "sources.view_rawitem",
        "sources.view_parsedarticlecandidate",
        "sources.view_article",
        "sources.view_story",
        "alerts.add_alert",
        "alerts.change_alert",
        "alerts.view_alert",
        "alerts.add_alertevent",
        "alerts.change_alertevent",
        "alerts.view_alertevent",
        "cases.add_case",
        "cases.change_case",
        "cases.view_case",
        "cases.add_casemember",
        "cases.change_casemember",
        "cases.view_casemember",
        "cases.add_casenote",
        "cases.change_casenote",
        "cases.view_casenote",
        "cases.add_casereference",
        "cases.change_casereference",
        "cases.view_casereference",
        "ops.view_auditlog",
    ),
    "intel_manager": (
        "accounts.view_userprofile",
        "topics.add_topic",
        "topics.change_topic",
        "topics.delete_topic",
        "topics.view_topic",
        "topics.add_watchlist",
        "topics.change_watchlist",
        "topics.delete_watchlist",
        "topics.view_watchlist",
        "topics.add_keywordrule",
        "topics.change_keywordrule",
        "topics.delete_keywordrule",
        "topics.view_keywordrule",
        "sources.view_source",
        "sources.view_sourcehealthevent",
        "sources.view_rawitem",
        "sources.view_parsedarticlecandidate",
        "sources.view_article",
        "sources.view_story",
        "alerts.add_alert",
        "alerts.change_alert",
        "alerts.delete_alert",
        "alerts.view_alert",
        "alerts.add_alertevent",
        "alerts.change_alertevent",
        "alerts.delete_alertevent",
        "alerts.view_alertevent",
        "cases.add_case",
        "cases.change_case",
        "cases.delete_case",
        "cases.view_case",
        "cases.add_casemember",
        "cases.change_casemember",
        "cases.delete_casemember",
        "cases.view_casemember",
        "cases.add_casenote",
        "cases.change_casenote",
        "cases.delete_casenote",
        "cases.view_casenote",
        "cases.add_casereference",
        "cases.change_casereference",
        "cases.delete_casereference",
        "cases.view_casereference",
        "ops.view_auditlog",
    ),
    "ops_operator": (
        "accounts.view_userprofile",
        "sources.add_source",
        "sources.change_source",
        "sources.view_source",
        "sources.add_sourcehealthevent",
        "sources.change_sourcehealthevent",
        "sources.view_sourcehealthevent",
        "sources.add_sourcefetchrun",
        "sources.change_sourcefetchrun",
        "sources.view_sourcefetchrun",
        "sources.add_sourcefetcherror",
        "sources.change_sourcefetcherror",
        "sources.view_sourcefetcherror",
        "sources.add_rawitem",
        "sources.change_rawitem",
        "sources.view_rawitem",
        "sources.add_parsedarticlecandidate",
        "sources.change_parsedarticlecandidate",
        "sources.view_parsedarticlecandidate",
        "sources.add_article",
        "sources.change_article",
        "sources.view_article",
        "sources.add_story",
        "sources.change_story",
        "sources.view_story",
        "alerts.view_alert",
        "alerts.view_alertevent",
        "ops.view_auditlog",
    ),
    "platform_admin": None,
}


def _permissions_from_codenames(codenames: Iterable[str]):
    permissions = []
    for item in codenames:
        app_label, codename = item.split(".", maxsplit=1)
        permissions.append(
            Permission.objects.select_related("content_type").get(
                content_type__app_label=app_label,
                codename=codename,
            )
        )
    return permissions


@transaction.atomic
def ensure_user_profiles(*, stdout) -> int:
    created = 0
    for user in User.objects.filter(profile__isnull=True):
        UserProfile.objects.create(user=user)
        created += 1
    stdout.write(f"Ensured user profiles. Created missing profiles: {created}")
    return created


@transaction.atomic
def sync_default_groups(*, stdout) -> None:
    for group_name, permission_codenames in DEFAULT_GROUP_PERMISSIONS.items():
        group, created = Group.objects.get_or_create(name=group_name)

        if group_name == "platform_admin":
            permissions = Permission.objects.filter(
                Q(content_type__app_label__in=CUSTOM_APP_LABELS)
                | Q(
                    content_type__app_label="auth",
                    codename__in=PLATFORM_ADMIN_AUTH_CODENAMES,
                )
            )
        elif permission_codenames is None:
            permissions = Permission.objects.filter(
                content_type__app_label__in=CUSTOM_APP_LABELS
            )
        else:
            permissions = _permissions_from_codenames(permission_codenames)

        group.permissions.set(permissions)
        action = "Created" if created else "Updated"
        stdout.write(f"{action} group '{group_name}' with {len(permissions)} permissions.")
