"""Neo4j Knowledge Graph Service — build a connected graph of intelligence entities.

Node labels
───────────
- :Source      {source_id, name, country, source_type, trust_score}
- :Article     {article_id, title, url, published_at, quality_score, importance_score}
- :Story       {story_id, title, article_count, importance_score}
- :Event       {event_id, title, event_type, confidence_score, conflict_flag}
- :Entity      {entity_id, name, canonical_name, entity_type, country}
- :Topic       {topic_id, name}
- :Location    {name, country, lat, lon}

Relationships
─────────────
- (Article)-[:PUBLISHED_BY]->(Source)
- (Article)-[:BELONGS_TO]->(Story)
- (Story)-[:PART_OF]->(Event)
- (Article)-[:MENTIONS {relevance, mention_count}]->(Entity)
- (Article)-[:MATCHED_TOPIC]->(Topic)
- (Event)-[:LOCATED_IN]->(Location)
"""
from __future__ import annotations

import logging

from services.integrations.neo4j_adapter import Neo4jAdapter

logger = logging.getLogger(__name__)


class Neo4jGraphService:
    """Build and maintain the knowledge graph in Neo4j."""

    def __init__(self):
        self._adapter: Neo4jAdapter | None = None

    @property
    def adapter(self) -> Neo4jAdapter:
        if self._adapter is None:
            self._adapter = Neo4jAdapter()
        return self._adapter

    # ── Bootstrap constraints / indexes ───────────────────────────

    def ensure_schema(self) -> None:
        """Create uniqueness constraints and indexes.  Idempotent."""
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Source) REQUIRE s.source_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Article) REQUIRE a.article_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (st:Story) REQUIRE st.story_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (e:Event) REQUIRE e.event_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (en:Entity) REQUIRE en.entity_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (t:Topic) REQUIRE t.topic_id IS UNIQUE",
        ]
        for cypher in constraints:
            try:
                self.adapter.write_graph(cypher)
            except Exception:
                logger.debug("Constraint may already exist: %s", cypher, exc_info=True)
        logger.info("Neo4j schema constraints ensured")

    # ── Write: Article + relationships ────────────────────────────

    def write_article(self, article) -> None:
        """Merge article node and all its relationships."""
        # 1. Source node
        source = article.source
        self.adapter.write_graph(
            """
            MERGE (s:Source {source_id: $sid})
            SET s.name        = $name,
                s.country     = $country,
                s.source_type = $stype,
                s.trust_score = $trust
            """,
            {
                "sid": source.id,
                "name": source.name,
                "country": source.country,
                "stype": source.source_type,
                "trust": float(source.trust_score),
            },
        )

        # 2. Article node
        self.adapter.write_graph(
            """
            MERGE (a:Article {article_id: $aid})
            SET a.title            = $title,
                a.url              = $url,
                a.published_at     = $pub,
                a.quality_score    = $quality,
                a.importance_score = $importance,
                a.is_duplicate     = $dup
            """,
            {
                "aid": article.id,
                "title": article.title,
                "url": article.url,
                "pub": article.published_at.isoformat() if article.published_at else None,
                "quality": float(article.quality_score),
                "importance": float(article.importance_score),
                "dup": article.is_duplicate,
            },
        )

        # 3. Article → Source
        self.adapter.write_graph(
            """
            MATCH (a:Article {article_id: $aid}), (s:Source {source_id: $sid})
            MERGE (a)-[:PUBLISHED_BY]->(s)
            """,
            {"aid": article.id, "sid": source.id},
        )

        # 4. Story node + relationship
        story = getattr(article, "story", None)
        if story:
            self.adapter.write_graph(
                """
                MERGE (st:Story {story_id: $stid})
                SET st.title          = $title,
                    st.article_count  = $cnt,
                    st.importance_score = $imp
                """,
                {
                    "stid": story.id,
                    "title": story.title,
                    "cnt": story.article_count,
                    "imp": float(story.importance_score),
                },
            )
            self.adapter.write_graph(
                """
                MATCH (a:Article {article_id: $aid}), (st:Story {story_id: $stid})
                MERGE (a)-[:BELONGS_TO]->(st)
                """,
                {"aid": article.id, "stid": story.id},
            )

            # 5. Event node + Story→Event
            if story.event_id:
                event = story.event
                self._write_event_node(event)
                self.adapter.write_graph(
                    """
                    MATCH (st:Story {story_id: $stid}), (e:Event {event_id: $eid})
                    MERGE (st)-[:PART_OF]->(e)
                    """,
                    {"stid": story.id, "eid": event.id},
                )

        # 6. Entity nodes + Article→Entity
        try:
            for ae in article.article_entities.select_related("entity").all():
                ent = ae.entity
                self.adapter.write_graph(
                    """
                    MERGE (en:Entity {entity_id: $enid})
                    SET en.name           = $name,
                        en.canonical_name = $canonical,
                        en.entity_type    = $etype,
                        en.country        = $country
                    """,
                    {
                        "enid": ent.id,
                        "name": ent.name,
                        "canonical": ent.canonical_name or ent.name,
                        "etype": ent.entity_type,
                        "country": ent.country,
                    },
                )
                self.adapter.write_graph(
                    """
                    MATCH (a:Article {article_id: $aid}), (en:Entity {entity_id: $enid})
                    MERGE (a)-[r:MENTIONS]->(en)
                    SET r.relevance     = $rel,
                        r.mention_count = $mc
                    """,
                    {
                        "aid": article.id,
                        "enid": ent.id,
                        "rel": float(ae.relevance_score),
                        "mc": ae.mention_count,
                    },
                )
        except Exception:
            logger.debug("Entity graph write skipped for article %s", article.id, exc_info=True)

        # 7. Topic nodes + Article→Topic
        try:
            for topic in article.matched_topics.all():
                self.adapter.write_graph(
                    """
                    MERGE (t:Topic {topic_id: $tid})
                    SET t.name = $name
                    """,
                    {"tid": topic.id, "name": topic.name},
                )
                self.adapter.write_graph(
                    """
                    MATCH (a:Article {article_id: $aid}), (t:Topic {topic_id: $tid})
                    MERGE (a)-[:MATCHED_TOPIC]->(t)
                    """,
                    {"aid": article.id, "tid": topic.id},
                )
        except Exception:
            logger.debug("Topic graph write skipped for article %s", article.id, exc_info=True)

    # ── Write: Event node (standalone) ────────────────────────────

    def _write_event_node(self, event) -> None:
        self.adapter.write_graph(
            """
            MERGE (e:Event {event_id: $eid})
            SET e.title            = $title,
                e.event_type       = $etype,
                e.confidence_score = $conf,
                e.conflict_flag    = $conflict,
                e.location_name    = $loc,
                e.location_country = $country,
                e.importance_score = $imp
            """,
            {
                "eid": event.id,
                "title": event.title,
                "etype": event.event_type,
                "conf": float(event.confidence_score),
                "conflict": event.conflict_flag,
                "loc": event.location_name,
                "country": event.location_country,
                "imp": float(event.importance_score),
            },
        )

        # Event → Location node
        if event.location_name:
            loc_params = {
                "name": event.location_name,
                "country": event.location_country,
            }
            if event.location_lat is not None:
                loc_params["lat"] = float(event.location_lat)
            if event.location_lon is not None:
                loc_params["lon"] = float(event.location_lon)

            self.adapter.write_graph(
                """
                MERGE (l:Location {name: $name})
                SET l.country = $country,
                    l.lat     = $lat,
                    l.lon     = $lon
                """,
                {
                    "name": event.location_name,
                    "country": event.location_country,
                    "lat": loc_params.get("lat"),
                    "lon": loc_params.get("lon"),
                },
            )
            self.adapter.write_graph(
                """
                MATCH (e:Event {event_id: $eid}), (l:Location {name: $lname})
                MERGE (e)-[:LOCATED_IN]->(l)
                """,
                {"eid": event.id, "lname": event.location_name},
            )
