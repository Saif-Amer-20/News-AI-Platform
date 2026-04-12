"""Tests for the Sources domain models."""
from __future__ import annotations

from decimal import Decimal

import pytest

from sources.models import Article, Entity, Event, Source, Story

from conftest import (
    ArticleFactory,
    EntityFactory,
    EventFactory,
    SourceFactory,
    StoryFactory,
)


@pytest.mark.django_db
class TestSource:
    def test_slug_auto_generated(self):
        s = SourceFactory(name="BBC News")
        assert s.slug
        assert "bbc" in s.slug.lower()

    def test_fetch_url_falls_back_to_base(self):
        s = SourceFactory(base_url="https://bbc.com/feed", endpoint_url="")
        assert s.fetch_url == "https://bbc.com/feed"

    def test_fetch_url_prefers_endpoint(self):
        s = SourceFactory(
            base_url="https://bbc.com",
            endpoint_url="https://bbc.com/api/feed",
        )
        assert s.fetch_url == "https://bbc.com/api/feed"

    def test_effective_fetch_interval(self):
        s = SourceFactory(fetch_interval_minutes=15, polling_interval_minutes=30)
        assert s.effective_fetch_interval() == 15


@pytest.mark.django_db
class TestStory:
    def test_slug_auto_generated(self):
        s = StoryFactory(title="Breaking political event")
        assert s.slug

    def test_story_key_unique(self):
        StoryFactory(story_key="abc123")
        with pytest.raises(Exception):
            StoryFactory(story_key="abc123")


@pytest.mark.django_db
class TestArticle:
    def test_article_relations(self, source):
        story = StoryFactory()
        article = ArticleFactory(source=source, story=story)
        assert article.source == source
        assert article.story == story

    def test_duplicate_flag(self, source):
        original = ArticleFactory(source=source)
        dup = ArticleFactory(source=source, is_duplicate=True, duplicate_of=original)
        assert dup.is_duplicate
        assert dup.duplicate_of == original


@pytest.mark.django_db
class TestEvent:
    def test_slug_auto_generated(self):
        e = EventFactory(title="Major earthquake")
        assert e.slug

    def test_conflict_flag_default(self):
        e = EventFactory()
        assert e.conflict_flag is False

    def test_geo_fields(self):
        e = EventFactory(
            location_lat=Decimal("33.513805"),
            location_lon=Decimal("36.276527"),
        )
        assert e.location_lat == Decimal("33.513805")


@pytest.mark.django_db
class TestEntity:
    def test_unique_constraint(self):
        EntityFactory(name="Entity A", normalized_name="entity a", entity_type="person")
        with pytest.raises(Exception):
            EntityFactory(name="Entity A copy", normalized_name="entity a", entity_type="person")

    def test_entity_type_choices(self):
        assert Entity.EntityType.PERSON == "person"
        assert Entity.EntityType.LOCATION == "location"
        assert Entity.EntityType.ORGANIZATION == "organization"
