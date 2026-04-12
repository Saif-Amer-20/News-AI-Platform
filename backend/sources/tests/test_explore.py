"""Tests for the Explore endpoints — Event Explorer, Entity Explorer,
Map, Timeline, and Graph (mocked)."""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from conftest import (
    ArticleEntityFactory,
    ArticleFactory,
    EntityFactory,
    EventFactory,
    SourceFactory,
    StoryFactory,
)


@pytest.mark.django_db
class TestEventExplorer:
    URL = "/api/v1/explore/explore-events/"

    def test_list_events(self, api_client):
        EventFactory.create_batch(3)
        resp = api_client.get(self.URL)
        assert resp.status_code == 200
        assert resp.data["count"] == 3

    def test_filter_by_event_type(self, api_client):
        EventFactory(event_type="protest")
        EventFactory(event_type="conflict")
        resp = api_client.get(self.URL, {"event_type": "protest"})
        assert resp.data["count"] == 1

    def test_filter_by_country(self, api_client):
        EventFactory(location_country="US")
        EventFactory(location_country="GB")
        resp = api_client.get(self.URL, {"country": "US"})
        assert resp.data["count"] == 1

    def test_filter_conflict(self, api_client):
        EventFactory(conflict_flag=True)
        EventFactory(conflict_flag=False)
        resp = api_client.get(self.URL, {"conflict": "true"})
        assert resp.data["count"] == 1

    def test_filter_min_confidence(self, api_client):
        EventFactory(confidence_score=Decimal("0.90"))
        EventFactory(confidence_score=Decimal("0.30"))
        resp = api_client.get(self.URL, {"min_confidence": "0.50"})
        assert resp.data["count"] == 1

    def test_timeline_action(self, api_client):
        ev = EventFactory(timeline_json=[{"ts": "2024-01-01T00:00:00Z", "type": "created"}])
        story = StoryFactory(event=ev)
        ArticleFactory(story=story, source=SourceFactory())
        resp = api_client.get(f"{self.URL}{ev.id}/timeline/")
        assert resp.status_code == 200
        assert "entries" in resp.data
        # Original timeline entry + article entry
        assert len(resp.data["entries"]) >= 1

    def test_sources_action(self, api_client):
        ev = EventFactory()
        s1 = SourceFactory(name="Reuters")
        s2 = SourceFactory(name="AP")
        story = StoryFactory(event=ev)
        ArticleFactory(story=story, source=s1)
        ArticleFactory(story=story, source=s2)
        resp = api_client.get(f"{self.URL}{ev.id}/sources/")
        assert resp.status_code == 200
        assert resp.data["total_sources"] == 2

    def test_entities_action(self, api_client):
        ev = EventFactory()
        story = StoryFactory(event=ev)
        art = ArticleFactory(story=story, source=SourceFactory())
        ent = EntityFactory(name="John Doe")
        ArticleEntityFactory(article=art, entity=ent)
        resp = api_client.get(f"{self.URL}{ev.id}/entities/")
        assert resp.status_code == 200
        assert len(resp.data["entities"]) == 1
        assert resp.data["entities"][0]["name"] == "John Doe"

    def test_related_action(self, api_client):
        ev1 = EventFactory(location_country="US")
        ev2 = EventFactory(location_country="US")  # same country → related
        EventFactory(location_country="JP")  # different country
        resp = api_client.get(f"{self.URL}{ev1.id}/related/")
        assert resp.status_code == 200
        related_ids = [e["id"] for e in resp.data["events"]]
        assert ev2.id in related_ids

    def test_articles_action(self, api_client):
        ev = EventFactory()
        story = StoryFactory(event=ev)
        ArticleFactory.create_batch(3, story=story, source=SourceFactory())
        resp = api_client.get(f"{self.URL}{ev.id}/articles/")
        assert resp.status_code == 200

    def test_hotspots(self, api_client):
        EventFactory(location_country="US")
        EventFactory(location_country="US")
        EventFactory(location_country="GB")
        resp = api_client.get(f"{self.URL}hotspots/")
        assert resp.status_code == 200
        assert resp.data["total_events"] == 3
        assert len(resp.data["by_country"]) == 2


@pytest.mark.django_db
class TestEntityExplorer:
    URL = "/api/v1/explore/explore-entities/"

    def test_list_entities(self, api_client):
        EntityFactory.create_batch(3)
        resp = api_client.get(self.URL)
        assert resp.status_code == 200
        assert resp.data["count"] == 3

    def test_filter_by_type(self, api_client):
        EntityFactory(entity_type="person")
        EntityFactory(entity_type="organization")
        resp = api_client.get(self.URL, {"entity_type": "person"})
        assert resp.data["count"] == 1

    def test_text_search(self, api_client):
        EntityFactory(name="John Doe")
        EntityFactory(name="Jane Smith")
        resp = api_client.get(self.URL, {"q": "john"})
        assert resp.data["count"] == 1

    def test_articles_action(self, api_client):
        ent = EntityFactory()
        art = ArticleFactory(source=SourceFactory())
        ArticleEntityFactory(article=art, entity=ent)
        resp = api_client.get(f"{self.URL}{ent.id}/articles/")
        assert resp.status_code == 200

    def test_events_action(self, api_client):
        ent = EntityFactory()
        ev = EventFactory()
        story = StoryFactory(event=ev)
        art = ArticleFactory(story=story, source=SourceFactory())
        ArticleEntityFactory(article=art, entity=ent)
        resp = api_client.get(f"{self.URL}{ent.id}/events/")
        assert resp.status_code == 200
        assert len(resp.data["events"]) == 1

    def test_co_occurrences(self, api_client):
        e1 = EntityFactory(name="Alice")
        e2 = EntityFactory(name="Bob")
        art = ArticleFactory(source=SourceFactory())
        ArticleEntityFactory(article=art, entity=e1)
        ArticleEntityFactory(article=art, entity=e2)
        resp = api_client.get(f"{self.URL}{e1.id}/co-occurrences/")
        assert resp.status_code == 200
        names = [c["co_entity_name"] for c in resp.data["co_occurrences"]]
        assert "Bob" in names

    def test_timeline_action(self, api_client):
        ent = EntityFactory()
        art = ArticleFactory(source=SourceFactory())
        ArticleEntityFactory(article=art, entity=ent)
        resp = api_client.get(f"{self.URL}{ent.id}/timeline/")
        assert resp.status_code == 200
        assert len(resp.data["entries"]) >= 1


@pytest.mark.django_db
class TestMapEndpoints:
    def test_map_events(self, api_client):
        EventFactory(
            location_lat=Decimal("38.90"), location_lon=Decimal("-77.03"),
        )
        EventFactory(location_lat=None, location_lon=None)  # excluded
        resp = api_client.get("/api/v1/explore/map/events/")
        assert resp.status_code == 200
        assert resp.data["type"] == "FeatureCollection"
        assert len(resp.data["features"]) == 1
        feat = resp.data["features"][0]
        assert feat["geometry"]["type"] == "Point"

    def test_map_events_filter(self, api_client):
        EventFactory(
            location_lat=Decimal("38.90"), location_lon=Decimal("-77.03"),
            event_type="protest",
        )
        EventFactory(
            location_lat=Decimal("51.50"), location_lon=Decimal("-0.12"),
            event_type="conflict",
        )
        resp = api_client.get("/api/v1/explore/map/events/", {"event_type": "protest"})
        assert len(resp.data["features"]) == 1

    def test_map_entities(self, api_client):
        EntityFactory(latitude=Decimal("40.71"), longitude=Decimal("-74.00"))
        EntityFactory(latitude=None, longitude=None)  # excluded
        resp = api_client.get("/api/v1/explore/map/entities/")
        assert resp.status_code == 200
        assert resp.data["type"] == "FeatureCollection"
        assert len(resp.data["features"]) == 1


@pytest.mark.django_db
class TestGlobalTimeline:
    def test_timeline(self, api_client):
        EventFactory.create_batch(3)
        resp = api_client.get("/api/v1/explore/timeline/")
        assert resp.status_code == 200
        assert resp.data["count"] == 3
        assert len(resp.data["entries"]) == 3

    def test_timeline_filters(self, api_client):
        EventFactory(event_type="protest")
        EventFactory(event_type="conflict")
        resp = api_client.get("/api/v1/explore/timeline/", {"event_type": "protest"})
        assert resp.data["count"] == 1


@pytest.mark.django_db
class TestGraphEndpoints:
    @patch("sources.views_explore.Neo4jAdapter")
    def test_graph_neighbors_validates_params(self, mock_adapter, api_client):
        resp = api_client.get("/api/v1/explore/graph/neighbors/")
        assert resp.status_code == 400

    @patch("sources.views_explore.Neo4jAdapter")
    def test_graph_neighbors_invalid_label(self, mock_adapter, api_client):
        resp = api_client.get(
            "/api/v1/explore/graph/neighbors/",
            {"label": "BadLabel", "id": "1"},
        )
        assert resp.status_code == 400

    def test_graph_shortest_path_validates_params(self, api_client):
        resp = api_client.get("/api/v1/explore/graph/path/")
        assert resp.status_code == 400
