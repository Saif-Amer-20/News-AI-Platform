"""Management command: migrate_graph_schema - Neo4j schema evolution
with constraint and index management."""
from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)

# Ordered list of schema migrations. Each entry is (version, description, up_cypher, down_cypher).
# Versions are monotonically increasing and are tracked in a :SchemaMeta node.
SCHEMA_MIGRATIONS: list[tuple[int, str, list[str], list[str]]] = [
    (
        1,
        "Initial constraints and indexes",
        [
            "CREATE CONSTRAINT source_id IF NOT EXISTS FOR (n:Source) REQUIRE n.source_id IS UNIQUE",
            "CREATE CONSTRAINT article_id IF NOT EXISTS FOR (n:Article) REQUIRE n.article_id IS UNIQUE",
            "CREATE CONSTRAINT story_id IF NOT EXISTS FOR (n:Story) REQUIRE n.story_id IS UNIQUE",
            "CREATE CONSTRAINT event_id IF NOT EXISTS FOR (n:Event) REQUIRE n.event_id IS UNIQUE",
            "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.entity_id IS UNIQUE",
            "CREATE CONSTRAINT topic_id IF NOT EXISTS FOR (n:Topic) REQUIRE n.topic_id IS UNIQUE",
            "CREATE CONSTRAINT location_name IF NOT EXISTS FOR (n:Location) REQUIRE n.name IS UNIQUE",
        ],
        [
            "DROP CONSTRAINT source_id IF EXISTS",
            "DROP CONSTRAINT article_id IF EXISTS",
            "DROP CONSTRAINT story_id IF EXISTS",
            "DROP CONSTRAINT event_id IF EXISTS",
            "DROP CONSTRAINT entity_id IF EXISTS",
            "DROP CONSTRAINT topic_id IF EXISTS",
            "DROP CONSTRAINT location_name IF EXISTS",
        ],
    ),
    (
        2,
        "Composite index for relationship traversal performance",
        [
            "CREATE INDEX source_type_idx IF NOT EXISTS FOR (n:Source) ON (n.source_type)",
            "CREATE INDEX event_type_idx IF NOT EXISTS FOR (n:Event) ON (n.event_type)",
            "CREATE INDEX entity_type_idx IF NOT EXISTS FOR (n:Entity) ON (n.entity_type)",
            "CREATE INDEX location_country_idx IF NOT EXISTS FOR (n:Location) ON (n.country)",
        ],
        [
            "DROP INDEX source_type_idx IF EXISTS",
            "DROP INDEX event_type_idx IF EXISTS",
            "DROP INDEX entity_type_idx IF EXISTS",
            "DROP INDEX location_country_idx IF EXISTS",
        ],
    ),
]


class Command(BaseCommand):
    help = "Manage Neo4j schema migrations: apply, rollback, and check status."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="subcommand")

        sub.add_parser("status", help="Show current schema version")
        sub.add_parser("upgrade", help="Apply all pending migrations")

        rollback = sub.add_parser("rollback", help="Rollback to a specific version")
        rollback.add_argument("--version", type=int, required=True)

    def handle(self, *args, **options):
        from services.integrations.neo4j_adapter import Neo4jAdapter

        self.adapter = Neo4jAdapter()
        try:
            subcmd = options.get("subcommand")
            if subcmd == "status":
                self._status()
            elif subcmd == "upgrade":
                self._upgrade()
            elif subcmd == "rollback":
                self._rollback(options["version"])
            else:
                self.stderr.write("Usage: manage.py migrate_graph_schema {status|upgrade|rollback}")
        finally:
            self.adapter.close()

    def _get_current_version(self) -> int:
        try:
            records = self.adapter.read_query(
                "MATCH (m:SchemaMeta) RETURN m.version AS version"
            )
            if records:
                return records[0]["version"]
        except Exception:
            pass
        return 0

    def _set_version(self, version: int):
        self.adapter.write_graph(
            "MERGE (m:SchemaMeta) SET m.version = $version, m.updated_at = datetime()",
            {"version": version},
        )

    def _status(self):
        current = self._get_current_version()
        latest = SCHEMA_MIGRATIONS[-1][0] if SCHEMA_MIGRATIONS else 0
        self.stdout.write(f"Current schema version: {current}")
        self.stdout.write(f"Latest available version: {latest}")
        if current < latest:
            pending = [m for m in SCHEMA_MIGRATIONS if m[0] > current]
            self.stdout.write(f"Pending migrations: {len(pending)}")
            for ver, desc, _, _ in pending:
                self.stdout.write(f"  v{ver}: {desc}")
        else:
            self.stdout.write(self.style.SUCCESS("Schema is up to date."))

    def _upgrade(self):
        current = self._get_current_version()
        pending = [m for m in SCHEMA_MIGRATIONS if m[0] > current]

        if not pending:
            self.stdout.write(self.style.SUCCESS("No pending migrations."))
            return

        for ver, desc, up_stmts, _ in pending:
            self.stdout.write(f"Applying v{ver}: {desc}")
            for stmt in up_stmts:
                try:
                    self.adapter.write_graph(stmt)
                except Exception as e:
                    self.stderr.write(self.style.ERROR(f"  Failed: {stmt}\n  Error: {e}"))
                    raise
            self._set_version(ver)
            self.stdout.write(self.style.SUCCESS(f"  v{ver} applied."))

        self.stdout.write(self.style.SUCCESS("All migrations applied."))

    def _rollback(self, target_version: int):
        current = self._get_current_version()
        if target_version >= current:
            self.stderr.write(f"Target version {target_version} >= current {current}.")
            return

        to_rollback = [
            m for m in reversed(SCHEMA_MIGRATIONS)
            if m[0] > target_version and m[0] <= current
        ]

        for ver, desc, _, down_stmts in to_rollback:
            self.stdout.write(f"Rolling back v{ver}: {desc}")
            for stmt in down_stmts:
                try:
                    self.adapter.write_graph(stmt)
                except Exception as e:
                    self.stderr.write(self.style.ERROR(f"  Failed: {stmt}\n  Error: {e}"))
                    raise
            self.stdout.write(self.style.SUCCESS(f"  v{ver} rolled back."))

        self._set_version(target_version)
        self.stdout.write(self.style.SUCCESS(f"Rolled back to v{target_version}."))
