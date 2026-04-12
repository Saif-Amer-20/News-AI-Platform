"""Management command: migrate_search_indices - Zero-downtime OpenSearch
index migration with versioning and rollback."""
from __future__ import annotations

import json
import logging
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Manage OpenSearch index versioning: create versioned indices, "
        "reindex data, swap aliases, and rollback."
    )

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="subcommand")

        # Status: show current indices and aliases
        sub.add_parser("status", help="Show current index versions and aliases")

        # Upgrade: create new version → reindex → swap alias
        upgrade = sub.add_parser("upgrade", help="Create a new index version and reindex")
        upgrade.add_argument("--index", required=True, choices=["articles", "events"])

        # Rollback: point alias back to previous version
        rollback = sub.add_parser("rollback", help="Rollback alias to previous index version")
        rollback.add_argument("--index", required=True, choices=["articles", "events"])

        # Cleanup: delete old index versions
        cleanup = sub.add_parser("cleanup", help="Delete old index versions (keeps current + 1 previous)")
        cleanup.add_argument("--index", required=True, choices=["articles", "events"])

    def handle(self, *args, **options):
        from services.integrations.opensearch_adapter import OpenSearchAdapter

        self.adapter = OpenSearchAdapter()
        self.client = self.adapter._client

        subcmd = options.get("subcommand")
        if subcmd == "status":
            self._status()
        elif subcmd == "upgrade":
            self._upgrade(options["index"])
        elif subcmd == "rollback":
            self._rollback(options["index"])
        elif subcmd == "cleanup":
            self._cleanup(options["index"])
        else:
            self.stderr.write("Usage: manage.py migrate_search_indices {status|upgrade|rollback|cleanup}")

    def _alias_name(self, index: str) -> str:
        return f"newsintel-{index}"

    def _get_versions(self, index: str) -> list[str]:
        """Return sorted list of concrete index names for a given alias prefix."""
        alias = self._alias_name(index)
        try:
            all_indices = self.client.cat.indices(format="json")
        except Exception:
            return []
        versions = [
            idx["index"]
            for idx in all_indices
            if idx["index"].startswith(f"{alias}-v")
        ]
        versions.sort()
        return versions

    def _current_alias_target(self, index: str) -> str | None:
        alias = self._alias_name(index)
        try:
            result = self.client.indices.get_alias(name=alias)
            return list(result.keys())[0] if result else None
        except Exception:
            return None

    def _status(self):
        for idx_type in ("articles", "events"):
            alias = self._alias_name(idx_type)
            current = self._current_alias_target(idx_type)
            versions = self._get_versions(idx_type)
            self.stdout.write(f"\n{'=' * 60}")
            self.stdout.write(f"Index: {alias}")
            self.stdout.write(f"Current alias target: {current or 'NOT SET'}")
            self.stdout.write(f"All versions: {versions or ['none']}")

            # Check if using unversioned index
            try:
                exists = self.client.indices.exists(index=alias)
                if exists:
                    is_alias = False
                    try:
                        self.client.indices.get_alias(name=alias)
                        is_alias = True
                    except Exception:
                        pass
                    if not is_alias:
                        self.stdout.write(
                            self.style.WARNING(
                                f"  ⚠ '{alias}' is a concrete index, not an alias. "
                                f"Run 'upgrade --index {idx_type}' to migrate to versioned indices."
                            )
                        )
            except Exception:
                pass
        self.stdout.write("")

    def _upgrade(self, index: str):
        from services.orchestration.opensearch_service import (
            ARTICLE_INDEX,
            ARTICLE_MAPPING,
            EVENT_INDEX,
            EVENT_MAPPING,
        )

        alias = self._alias_name(index)
        mapping = ARTICLE_MAPPING if index == "articles" else EVENT_MAPPING
        versions = self._get_versions(index)

        # Determine version number
        if versions:
            last = versions[-1]
            last_ver = int(last.rsplit("-v", 1)[1])
            new_ver = last_ver + 1
        else:
            new_ver = 1

        new_index_name = f"{alias}-v{new_ver}"
        old_target = self._current_alias_target(index)

        self.stdout.write(f"Creating new index: {new_index_name}")
        try:
            self.client.indices.create(index=new_index_name, body=mapping)
        except Exception as e:
            raise CommandError(f"Failed to create index: {e}")

        # Reindex from old index (alias target or concrete index) to new
        source_index = old_target or alias
        try:
            source_exists = self.client.indices.exists(index=source_index)
        except Exception:
            source_exists = False

        if source_exists:
            self.stdout.write(f"Reindexing from '{source_index}' → '{new_index_name}' ...")
            try:
                result = self.client.reindex(
                    body={
                        "source": {"index": source_index},
                        "dest": {"index": new_index_name},
                    },
                    request_timeout=600,
                )
                total = result.get("total", 0)
                self.stdout.write(f"  Reindexed {total} documents.")
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Reindex failed: {e}"))
                self.stderr.write("Cleaning up new index ...")
                self.client.indices.delete(index=new_index_name, ignore=[404])
                raise CommandError("Upgrade aborted.")

        # Swap alias atomically
        actions = []

        # If alias currently points somewhere, remove it
        if old_target:
            actions.append({"remove": {"index": old_target, "alias": alias}})

        # If the alias name is actually a concrete index, delete it first
        if not old_target:
            try:
                exists = self.client.indices.exists(index=alias)
                if exists:
                    # Check if it's a concrete index (not an alias)
                    is_alias = False
                    try:
                        self.client.indices.get_alias(name=alias)
                        is_alias = True
                    except Exception:
                        pass
                    if not is_alias:
                        self.stdout.write(f"Deleting concrete index '{alias}' to create alias ...")
                        self.client.indices.delete(index=alias)
            except Exception:
                pass

        actions.append({"add": {"index": new_index_name, "alias": alias}})

        self.client.indices.update_aliases(body={"actions": actions})
        self.stdout.write(self.style.SUCCESS(f"Alias '{alias}' → '{new_index_name}'"))

    def _rollback(self, index: str):
        alias = self._alias_name(index)
        versions = self._get_versions(index)
        current = self._current_alias_target(index)

        if len(versions) < 2:
            raise CommandError(f"No previous version to rollback to (versions: {versions})")

        if current and current in versions:
            idx = versions.index(current)
            if idx == 0:
                raise CommandError("Already at the oldest version.")
            previous = versions[idx - 1]
        else:
            previous = versions[-2]

        actions = []
        if current:
            actions.append({"remove": {"index": current, "alias": alias}})
        actions.append({"add": {"index": previous, "alias": alias}})

        self.client.indices.update_aliases(body={"actions": actions})
        self.stdout.write(self.style.SUCCESS(f"Rolled back alias '{alias}' → '{previous}'"))

    def _cleanup(self, index: str):
        alias = self._alias_name(index)
        current = self._current_alias_target(index)
        versions = self._get_versions(index)

        # Keep current + one before it
        to_keep = set()
        if current:
            to_keep.add(current)
            if current in versions:
                idx = versions.index(current)
                if idx > 0:
                    to_keep.add(versions[idx - 1])

        to_delete = [v for v in versions if v not in to_keep]
        if not to_delete:
            self.stdout.write("Nothing to clean up.")
            return

        for old in to_delete:
            self.stdout.write(f"Deleting old index: {old}")
            self.client.indices.delete(index=old, ignore=[404])

        self.stdout.write(self.style.SUCCESS(f"Cleaned up {len(to_delete)} old versions."))
