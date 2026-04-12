"""Management command: audit_permissions - Validate RBAC group permissions
match the expected configuration and detect drift."""
from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

from accounts.rbac import CUSTOM_APP_LABELS, DEFAULT_GROUP_PERMISSIONS, PLATFORM_ADMIN_AUTH_CODENAMES

logger = logging.getLogger(__name__)
User = get_user_model()


class Command(BaseCommand):
    help = (
        "Audit RBAC permissions: compare actual group permissions with "
        "expected configuration. Detect drift, orphaned permissions, "
        "and users without groups."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--fix",
            action="store_true",
            help="Automatically fix permission drift (re-sync groups).",
        )

    def handle(self, *args, **options):
        fix = options.get("fix", False)
        issues = []

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write("RBAC Permission Audit")
        self.stdout.write(f"{'=' * 60}")

        # 1. Check all expected groups exist
        issues += self._audit_groups()

        # 2. Check permissions match expectations
        issues += self._audit_group_permissions()

        # 3. Check for users without any group
        issues += self._audit_ungrouped_users()

        # 4. Check for superusers
        issues += self._audit_superusers()

        # 5. Check for staff users outside platform_admin
        issues += self._audit_staff_users()

        # Summary
        self.stdout.write(f"\n{'=' * 60}")
        if not issues:
            self.stdout.write(self.style.SUCCESS("No issues found. RBAC configuration is clean."))
        else:
            self.stdout.write(self.style.WARNING(f"Found {len(issues)} issue(s):"))
            for issue in issues:
                self.stdout.write(f"  - {issue}")

            if fix:
                self.stdout.write("\nApplying fixes ...")
                from accounts.rbac import sync_default_groups
                sync_default_groups(stdout=self.stdout)
                self.stdout.write(self.style.SUCCESS("Permissions re-synced."))

    def _audit_groups(self) -> list[str]:
        issues = []
        self.stdout.write("\n1. Group existence check:")
        for group_name in DEFAULT_GROUP_PERMISSIONS:
            exists = Group.objects.filter(name=group_name).exists()
            if exists:
                self.stdout.write(f"   {group_name}: exists")
            else:
                msg = f"Group '{group_name}' does not exist"
                issues.append(msg)
                self.stdout.write(self.style.ERROR(f"   {group_name}: MISSING"))
        return issues

    def _audit_group_permissions(self) -> list[str]:
        issues = []
        self.stdout.write("\n2. Permission drift check:")

        for group_name, expected_codenames in DEFAULT_GROUP_PERMISSIONS.items():
            try:
                group = Group.objects.get(name=group_name)
            except Group.DoesNotExist:
                continue

            actual_perms = set(
                group.permissions.select_related("content_type").values_list(
                    "content_type__app_label", "codename"
                )
            )
            actual_codenames = {f"{app}.{code}" for app, code in actual_perms}

            if group_name == "platform_admin":
                # platform_admin gets all custom app perms + auth perms
                expected_set = set(
                    Permission.objects.filter(
                        content_type__app_label__in=CUSTOM_APP_LABELS
                    ).values_list("content_type__app_label", "codename")
                )
                expected_set |= set(
                    Permission.objects.filter(
                        content_type__app_label="auth",
                        codename__in=PLATFORM_ADMIN_AUTH_CODENAMES,
                    ).values_list("content_type__app_label", "codename")
                )
                expected_codename_set = {f"{app}.{code}" for app, code in expected_set}
            elif expected_codenames is None:
                expected_codename_set = set(
                    f"{app}.{code}"
                    for app, code in Permission.objects.filter(
                        content_type__app_label__in=CUSTOM_APP_LABELS
                    ).values_list("content_type__app_label", "codename")
                )
            else:
                expected_codename_set = set(expected_codenames)

            missing = expected_codename_set - actual_codenames
            extra = actual_codenames - expected_codename_set

            if not missing and not extra:
                self.stdout.write(
                    f"   {group_name}: OK ({len(actual_codenames)} permissions)"
                )
            else:
                if missing:
                    msg = f"Group '{group_name}' missing permissions: {sorted(missing)}"
                    issues.append(msg)
                    self.stdout.write(self.style.WARNING(f"   {group_name}: MISSING {sorted(missing)}"))
                if extra:
                    msg = f"Group '{group_name}' has extra permissions: {sorted(extra)}"
                    issues.append(msg)
                    self.stdout.write(self.style.WARNING(f"   {group_name}: EXTRA {sorted(extra)}"))

        return issues

    def _audit_ungrouped_users(self) -> list[str]:
        issues = []
        self.stdout.write("\n3. Ungrouped users check:")
        ungrouped = User.objects.filter(
            groups__isnull=True,
            is_active=True,
            is_superuser=False,
        )
        count = ungrouped.count()
        if count == 0:
            self.stdout.write("   All active users have group assignments.")
        else:
            usernames = list(ungrouped.values_list("username", flat=True)[:20])
            msg = f"{count} active user(s) without any group: {usernames}"
            issues.append(msg)
            self.stdout.write(self.style.WARNING(f"   {msg}"))
        return issues

    def _audit_superusers(self) -> list[str]:
        issues = []
        self.stdout.write("\n4. Superuser check:")
        superusers = User.objects.filter(is_superuser=True, is_active=True)
        count = superusers.count()
        if count == 0:
            self.stdout.write("   No active superusers.")
        else:
            names = list(superusers.values_list("username", flat=True))
            self.stdout.write(f"   Active superusers ({count}): {names}")
            if count > 3:
                issues.append(f"High number of superusers: {count}")

        return issues

    def _audit_staff_users(self) -> list[str]:
        issues = []
        self.stdout.write("\n5. Staff user check:")
        staff_not_admin = User.objects.filter(
            is_staff=True, is_active=True,
        ).exclude(
            groups__name="platform_admin",
        ).exclude(is_superuser=True)
        count = staff_not_admin.count()
        if count == 0:
            self.stdout.write("   All staff users are in platform_admin or are superusers.")
        else:
            names = list(staff_not_admin.values_list("username", flat=True)[:20])
            msg = f"{count} staff user(s) not in platform_admin group: {names}"
            issues.append(msg)
            self.stdout.write(self.style.WARNING(f"   {msg}"))
        return issues
