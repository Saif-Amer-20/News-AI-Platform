"""Shared test fixtures and model factories."""
from __future__ import annotations

import datetime
from decimal import Decimal

import factory
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


# ═══════════════════════════════════════════════════════════════════════════════
# Factories
# ═══════════════════════════════════════════════════════════════════════════════


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    username = factory.Sequence(lambda n: f"user_{n}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.com")
    password = factory.PostGenerationMethodCall("set_password", "testpass123")


class TopicFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "topics.Topic"

    name = factory.Sequence(lambda n: f"Topic {n}")
    status = "active"
    priority = "medium"


class KeywordRuleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "topics.KeywordRule"

    topic = factory.SubFactory(TopicFactory)
    label = factory.Sequence(lambda n: f"rule-{n}")
    pattern = "test"
    rule_type = "keyword"
    match_target = "any"
    priority = "medium"
    enabled = True


class SourceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "sources.Source"

    name = factory.Sequence(lambda n: f"Source {n}")
    source_type = "rss"
    parser_type = "rss"
    base_url = factory.Sequence(lambda n: f"https://source-{n}.example.com/feed")
    country = "US"
    language = "en"
    trust_score = Decimal("0.75")


class SourceFetchRunFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "sources.SourceFetchRun"

    source = factory.SubFactory(SourceFactory)
    status = "completed"
    items_fetched = 10
    items_created = 5


class StoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "sources.Story"

    title = factory.Sequence(lambda n: f"Story {n}")
    story_key = factory.Sequence(lambda n: f"story_key_{n:06d}")
    article_count = 1
    importance_score = Decimal("0.50")
    first_published_at = factory.LazyFunction(timezone.now)
    last_published_at = factory.LazyFunction(timezone.now)


class EventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "sources.Event"

    title = factory.Sequence(lambda n: f"Event {n}")
    event_type = "political"
    location_name = "Washington D.C."
    location_country = "US"
    location_lat = Decimal("38.907192")
    location_lon = Decimal("-77.036873")
    importance_score = Decimal("0.60")
    confidence_score = Decimal("0.70")
    story_count = 1
    source_count = 1
    first_reported_at = factory.LazyFunction(timezone.now)
    last_reported_at = factory.LazyFunction(timezone.now)


class ArticleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "sources.Article"

    source = factory.SubFactory(SourceFactory)
    story = factory.SubFactory(StoryFactory)
    title = factory.Sequence(lambda n: f"Article {n}")
    normalized_title = factory.LazyAttribute(lambda o: o.title.lower())
    url = factory.Sequence(lambda n: f"https://example.com/article-{n}")
    content = factory.Sequence(lambda n: f"Content of article {n}.")
    normalized_content = factory.LazyAttribute(lambda o: o.content.lower())
    content_hash = factory.Sequence(lambda n: f"{n:064x}")
    published_at = factory.LazyFunction(timezone.now)
    quality_score = Decimal("0.80")
    importance_score = Decimal("0.60")


class EntityFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "sources.Entity"

    name = factory.Sequence(lambda n: f"Entity {n}")
    normalized_name = factory.LazyAttribute(lambda o: o.name.lower())
    entity_type = "person"
    country = "US"


class ArticleEntityFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "sources.ArticleEntity"

    article = factory.SubFactory(ArticleFactory)
    entity = factory.SubFactory(EntityFactory)
    relevance_score = Decimal("0.80")
    mention_count = 3


class AlertFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "alerts.Alert"

    title = factory.Sequence(lambda n: f"Alert {n}")
    alert_type = "keyword_match"
    severity = "medium"
    status = "open"
    summary = factory.Sequence(lambda n: f"Summary for alert {n}")
    rationale = "Test rationale"
    dedup_key = factory.Sequence(lambda n: f"dedup_{n:032x}")


class CaseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "cases.Case"

    title = factory.Sequence(lambda n: f"Case {n}")
    description = "Test case"
    status = "open"
    priority = "medium"


class SavedSearchFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "cases.SavedSearch"

    name = factory.Sequence(lambda n: f"Search {n}")
    search_type = "article"
    query_params = {"q": "test"}
    is_global = False


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def user(db):
    return UserFactory()


@pytest.fixture
def source(db):
    return SourceFactory()


@pytest.fixture
def topic(db):
    return TopicFactory()


@pytest.fixture
def event(db):
    story = StoryFactory()
    ev = EventFactory()
    story.event = ev
    story.save()
    return ev


@pytest.fixture
def article(db, source):
    story = StoryFactory()
    return ArticleFactory(source=source, story=story)


@pytest.fixture
def entity(db):
    return EntityFactory()


@pytest.fixture
def alert(db, source, topic):
    return AlertFactory(source=source, topic=topic)


@pytest.fixture
def case(db, user):
    return CaseFactory(owner=user, created_by=user)


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient
    return APIClient()


@pytest.fixture
def auth_client(api_client, user):
    api_client.force_authenticate(user=user)
    return api_client
