"""Tests for Sources domain API endpoints."""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse

from conftest import (
    ArticleEntityFactory,
    ArticleFactory,
    EntityFactory,
    EventFactory,
    SourceFactory,
    SourceFetchRunFactory,
    StoryFactory,
)


@pytest.mark.django_db
class TestSourceAPI:
    def test_list_sources(self, api_client):
        SourceFactory.create_batch(3)
        resp = api_client.get("/api/v1/sources/")
        assert resp.status_code == 200
        assert resp.data["count"] == 3

    def test_source_detail(self, api_client, source):
        resp = api_client.get(f"/api/v1/sources/{source.id}/")
        assert resp.status_code == 200
        assert resp.data["name"] == source.name

    def test_fetch_runs(self, api_client, source):
        SourceFetchRunFactory.create_batch(2, source=source)
        resp = api_client.get(f"/api/v1/sources/{source.id}/fetch-runs/")
        assert resp.status_code == 200
        assert len(resp.data) == 2

    def test_source_search(self, api_client):
        SourceFactory(name="BBC World News")
        SourceFactory(name="Al Jazeera")
        resp = api_client.get("/api/v1/sources/?search=BBC")
        assert resp.status_code == 200
        assert resp.data["count"] == 1


@pytest.mark.django_db
class TestArticleAPI:
    def test_list_articles(self, api_client, source):
        ArticleFactory.create_batch(3, source=source)
        resp = api_client.get("/api/v1/articles/")
        assert resp.status_code == 200
        assert resp.data["count"] == 3

    def test_filter_by_source(self, api_client):
        s1 = SourceFactory()
        s2 = SourceFactory()
        ArticleFactory.create_batch(2, source=s1)
        ArticleFactory(source=s2)
        resp = api_client.get(f"/api/v1/articles/?source={s1.id}")
        assert resp.status_code == 200
        assert resp.data["count"] == 2

    def test_filter_by_min_quality(self, api_client, source):
        ArticleFactory(source=source, quality_score=Decimal("0.90"))
        ArticleFactory(source=source, quality_score=Decimal("0.30"))
        resp = api_client.get("/api/v1/articles/?min_quality=0.50")
        assert resp.status_code == 200
        assert resp.data["count"] == 1

    def test_article_detail_includes_entities(self, api_client, source):
        article = ArticleFactory(source=source)
        entity = EntityFactory()
        ArticleEntityFactory(article=article, entity=entity)
        resp = api_client.get(f"/api/v1/articles/{article.id}/")
        assert resp.status_code == 200
        assert len(resp.data["entities"]) == 1

    def test_duplicates_excluded_by_default(self, api_client, source):
        original = ArticleFactory(source=source)
        ArticleFactory(source=source, is_duplicate=True, duplicate_of=original)
        resp = api_client.get("/api/v1/articles/")
        assert resp.data["count"] == 1


@pytest.mark.django_db
class TestStoryAPI:
    def test_list_stories(self, api_client):
        StoryFactory.create_batch(3)
        resp = api_client.get("/api/v1/stories/")
        assert resp.status_code == 200
        assert resp.data["count"] == 3

    def test_filter_by_event(self, api_client):
        ev = EventFactory()
        StoryFactory(event=ev)
        StoryFactory()
        resp = api_client.get(f"/api/v1/stories/?event={ev.id}")
        assert resp.data["count"] == 1


@pytest.mark.django_db
class TestEventAPI:
    def test_list_events(self, api_client):
        EventFactory.create_batch(3)
        resp = api_client.get("/api/v1/events/")
        assert resp.status_code == 200
        assert resp.data["count"] == 3

    def test_filter_by_type(self, api_client):
        EventFactory(event_type="protest")
        EventFactory(event_type="conflict")
        resp = api_client.get("/api/v1/events/?event_type=protest")
        assert resp.data["count"] == 1

    def test_conflicts_action(self, api_client):
        EventFactory(conflict_flag=True)
        EventFactory(conflict_flag=False)
        resp = api_client.get("/api/v1/events/conflicts/")
        assert resp.status_code == 200
        assert len(resp.data) == 1


@pytest.mark.django_db
class TestEntityAPI:
    def test_list_entities(self, api_client):
        EntityFactory.create_batch(3)
        resp = api_client.get("/api/v1/entities/")
        assert resp.status_code == 200
        assert resp.data["count"] == 3

    def test_filter_by_type(self, api_client):
        EntityFactory(entity_type="person")
        EntityFactory(entity_type="location")
        resp = api_client.get("/api/v1/entities/?entity_type=person")
        assert resp.data["count"] == 1
