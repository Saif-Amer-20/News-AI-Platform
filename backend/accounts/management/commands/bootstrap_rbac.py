from django.core.management.base import BaseCommand

from accounts.rbac import ensure_user_profiles, sync_default_groups


class Command(BaseCommand):
    help = "Creates baseline analyst, manager, operations, and platform admin groups."

    def handle(self, *args, **options):
        ensure_user_profiles(stdout=self.stdout)
        sync_default_groups(stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS("RBAC bootstrap complete."))

