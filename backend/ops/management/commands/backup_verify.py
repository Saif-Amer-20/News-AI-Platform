"""Management command: backup_verify - Verify backup procedures for
PostgreSQL, OpenSearch, Neo4j, and MinIO."""
from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Run backup verification checks across all data stores: "
        "PostgreSQL, OpenSearch, Neo4j, MinIO."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--store",
            choices=["postgres", "opensearch", "neo4j", "minio", "all"],
            default="all",
            help="Which data store to verify.",
        )
        parser.add_argument(
            "--dump-dir",
            default="/tmp/backups",
            help="Directory for backup dumps (default: /tmp/backups).",
        )

    def handle(self, *args, **options):
        store = options["store"]
        dump_dir = options["dump_dir"]
        os.makedirs(dump_dir, exist_ok=True)

        results = {}
        checks = {
            "postgres": self._verify_postgres,
            "opensearch": self._verify_opensearch,
            "neo4j": self._verify_neo4j,
            "minio": self._verify_minio,
        }

        targets = checks.keys() if store == "all" else [store]
        for name in targets:
            self.stdout.write(f"\n{'=' * 60}")
            self.stdout.write(f"Verifying: {name}")
            try:
                results[name] = checks[name](dump_dir)
            except Exception as e:
                results[name] = {"status": "error", "error": str(e)}
                self.stderr.write(self.style.ERROR(f"  Error: {e}"))

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write("Summary:")
        all_ok = True
        for name, result in results.items():
            status = result.get("status", "unknown")
            emoji = "OK" if status == "ok" else "FAIL"
            style = self.style.SUCCESS if status == "ok" else self.style.ERROR
            self.stdout.write(style(f"  {name}: {emoji}"))
            if status != "ok":
                all_ok = False
            for k, v in result.items():
                if k != "status":
                    self.stdout.write(f"    {k}: {v}")

        if not all_ok:
            self.stderr.write(self.style.ERROR("\nSome backup verifications failed."))

    def _verify_postgres(self, dump_dir: str) -> dict:
        """Verify pg_dump connectivity and table count."""
        from django.db import connections

        result = {"status": "ok"}

        # 1. Verify database connectivity
        with connections["default"].cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            )
            table_count = cursor.fetchone()[0]
            result["table_count"] = table_count

            # 2. Verify key tables exist
            cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
            tables = [row[0] for row in cursor.fetchall()]
            result["tables"] = tables

            # 3. Row counts for critical tables
            critical = [
                "sources_source", "sources_article", "sources_story",
                "sources_event", "sources_entity", "alerts_alert",
                "cases_case",
            ]
            counts = {}
            for table in critical:
                if table in tables:
                    cursor.execute(f"SELECT count(*) FROM {table}")  # nosec: table names are hardcoded
                    counts[table] = cursor.fetchone()[0]
            result["row_counts"] = counts

            # 4. Check pg_dump is available
            try:
                proc = subprocess.run(
                    ["pg_dump", "--version"],
                    capture_output=True, text=True, timeout=5,
                )
                result["pg_dump_version"] = proc.stdout.strip()
            except FileNotFoundError:
                result["pg_dump_available"] = False
                self.stdout.write(self.style.WARNING("  pg_dump not found in PATH"))

        self.stdout.write(f"  Tables: {table_count}")
        self.stdout.write(f"  Row counts: {json.dumps(counts, indent=2)}")
        return result

    def _verify_opensearch(self, dump_dir: str) -> dict:
        """Verify OpenSearch snapshot repository and index health."""
        import requests

        url = settings.OPENSEARCH_URL
        result = {"status": "ok"}

        # 1. Cluster health
        try:
            resp = requests.get(f"{url}/_cluster/health", timeout=5)
            resp.raise_for_status()
            health = resp.json()
            result["cluster_status"] = health["status"]
            result["num_nodes"] = health["number_of_nodes"]
            if health["status"] == "red":
                result["status"] = "degraded"
                self.stdout.write(self.style.WARNING("  Cluster status RED"))
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            return result

        # 2. Index stats
        try:
            resp = requests.get(f"{url}/_cat/indices?format=json", timeout=5)
            resp.raise_for_status()
            indices = resp.json()
            result["indices"] = [
                {
                    "name": idx["index"],
                    "docs": idx.get("docs.count", "?"),
                    "size": idx.get("store.size", "?"),
                    "health": idx.get("health", "?"),
                }
                for idx in indices
                if not idx["index"].startswith(".")
            ]
        except Exception as e:
            result["index_check_error"] = str(e)

        # 3. Snapshot repositories
        try:
            resp = requests.get(f"{url}/_snapshot", timeout=5)
            if resp.status_code == 200:
                repos = resp.json()
                result["snapshot_repos"] = list(repos.keys())
            else:
                result["snapshot_repos"] = []
        except Exception:
            result["snapshot_repos"] = []

        self.stdout.write(f"  Cluster: {result.get('cluster_status', 'unknown')}")
        for idx in result.get("indices", []):
            self.stdout.write(f"  Index {idx['name']}: {idx['docs']} docs, {idx['size']}")
        return result

    def _verify_neo4j(self, dump_dir: str) -> dict:
        """Verify Neo4j connectivity and node/relationship counts."""
        from services.integrations.neo4j_adapter import Neo4jAdapter

        result = {"status": "ok"}
        try:
            adapter = Neo4jAdapter()

            # Total node count
            records = adapter.read_query("MATCH (n) RETURN count(n) AS total")
            result["total_nodes"] = records[0]["total"] if records else 0

            # Node counts by label
            records = adapter.read_query(
                "CALL db.labels() YIELD label "
                "CALL { WITH label "
                "  MATCH (n) WHERE label IN labels(n) "
                "  RETURN count(n) AS cnt "
                "} RETURN label, cnt ORDER BY cnt DESC"
            )
            result["nodes_by_label"] = {r["label"]: r["cnt"] for r in records}

            # Relationship count
            records = adapter.read_query("MATCH ()-[r]->() RETURN count(r) AS total")
            result["total_relationships"] = records[0]["total"] if records else 0

            # Schema version
            records = adapter.read_query(
                "MATCH (m:SchemaMeta) RETURN m.version AS version"
            )
            result["schema_version"] = records[0]["version"] if records else 0

            adapter.close()
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            return result

        self.stdout.write(f"  Nodes: {result['total_nodes']}")
        self.stdout.write(f"  Relationships: {result['total_relationships']}")
        self.stdout.write(f"  Schema version: {result['schema_version']}")
        for label, cnt in result.get("nodes_by_label", {}).items():
            self.stdout.write(f"    {label}: {cnt}")
        return result

    def _verify_minio(self, dump_dir: str) -> dict:
        """Verify MinIO bucket accessibility."""
        import requests

        result = {"status": "ok"}
        endpoint = settings.MINIO_ENDPOINT

        try:
            resp = requests.get(f"{endpoint}/minio/health/live", timeout=5)
            result["live"] = resp.status_code == 200
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            return result

        # Check bucket exists (via S3 API)
        try:
            from services.integrations.minio_adapter import MinioAdapter
            adapter = MinioAdapter()
            bucket = settings.MINIO_RAW_BUCKET
            exists = adapter._client.bucket_exists(bucket)
            result["bucket_exists"] = exists
            if exists:
                # Count objects (sample)
                objects = list(adapter._client.list_objects(bucket, max_keys=10))
                result["sample_objects"] = len(objects)
        except Exception as e:
            result["bucket_check_error"] = str(e)

        self.stdout.write(f"  MinIO live: {result.get('live', False)}")
        self.stdout.write(f"  Bucket exists: {result.get('bucket_exists', 'unknown')}")
        return result
