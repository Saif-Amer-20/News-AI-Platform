"""Neo4j graph database integration adapter."""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from neo4j import GraphDatabase

from .common import BaseAdapter, IntegrationError

logger = logging.getLogger(__name__)


class Neo4jAdapter(BaseAdapter):
    service_name = "neo4j"

    def __init__(self):
        uri = getattr(settings, "NEO4J_URI", "bolt://neo4j:7687")
        user = getattr(settings, "NEO4J_USER", "neo4j")
        password = getattr(settings, "NEO4J_PASSWORD", "")
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self._driver.close()

    # ── Write operations ──────────────────────────────────────────────

    def write_graph(self, cypher: str, parameters: dict | None = None) -> list[dict]:
        try:
            with self._driver.session() as session:
                result = session.run(cypher, parameters or {})
                return [record.data() for record in result]
        except Exception as exc:
            raise IntegrationError(f"Neo4j write failed: {exc}") from exc

    def merge_node(self, label: str, key_props: dict, extra_props: dict | None = None) -> dict:
        set_clause = ""
        params: dict[str, Any] = {"key_props": key_props}
        if extra_props:
            set_clause = "SET n += $extra_props"
            params["extra_props"] = extra_props
        cypher = f"MERGE (n:{label} $key_props) {set_clause} RETURN n"
        return self.write_graph(cypher, params)

    def merge_relationship(
        self,
        from_label: str,
        from_key: dict,
        to_label: str,
        to_key: dict,
        rel_type: str,
        rel_props: dict | None = None,
    ) -> list[dict]:
        params = {
            "from_key": from_key,
            "to_key": to_key,
            "rel_props": rel_props or {},
        }
        cypher = (
            f"MATCH (a:{from_label} $from_key), (b:{to_label} $to_key) "
            f"MERGE (a)-[r:{rel_type}]->(b) SET r += $rel_props RETURN r"
        )
        return self.write_graph(cypher, params)

    # ── Read operations ───────────────────────────────────────────────

    def read_query(self, cypher: str, parameters: dict | None = None) -> list[dict]:
        try:
            with self._driver.session() as session:
                result = session.run(cypher, parameters or {})
                return [record.data() for record in result]
        except Exception as exc:
            raise IntegrationError(f"Neo4j read failed: {exc}") from exc

    # ── Health ────────────────────────────────────────────────────────

    def health(self) -> bool:
        try:
            self._driver.verify_connectivity()
            return True
        except Exception as exc:
            raise IntegrationError(f"Neo4j health check failed: {exc}") from exc
