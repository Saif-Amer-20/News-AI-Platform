"""Tests for Alerts API endpoints."""
from __future__ import annotations

import pytest
from django.utils import timezone

from conftest import AlertFactory, ArticleFactory, EventFactory, SourceFactory, StoryFactory


@pytest.mark.django_db
class TestAlertList:
    URL = "/api/v1/alerts/"

    def test_list(self, api_client):
        AlertFactory.create_batch(3)
        resp = api_client.get(self.URL)
        assert resp.status_code == 200
        assert resp.data["count"] == 3

    def test_filter_by_type(self, api_client):
        AlertFactory(alert_type="keyword_match")
        AlertFactory(alert_type="story_update")
        resp = api_client.get(self.URL, {"alert_type": "keyword_match"})
        assert resp.data["count"] == 1

    def test_filter_by_severity(self, api_client):
        AlertFactory(severity="critical")
        AlertFactory(severity="low")
        resp = api_client.get(self.URL, {"severity": "critical"})
        assert resp.data["count"] == 1

    def test_filter_by_status(self, api_client):
        AlertFactory(status="open")
        AlertFactory(status="resolved")
        resp = api_client.get(self.URL, {"status": "open"})
        assert resp.data["count"] == 1

    def test_detail(self, api_client):
        a = AlertFactory()
        resp = api_client.get(f"{self.URL}{a.id}/")
        assert resp.status_code == 200
        assert resp.data["title"] == a.title


@pytest.mark.django_db
class TestAlertExplain:
    URL = "/api/v1/alerts/"

    def test_explain_basic(self, api_client):
        a = AlertFactory(
            alert_type="keyword_match",
            rationale="Matched keywords on topic.",
            metadata={},
        )
        resp = api_client.get(f"{self.URL}{a.id}/explain/")
        assert resp.status_code == 200
        assert resp.data["alert_type"] == "keyword_match"
        assert resp.data["rationale"] == a.rationale
        assert "recommended_actions" in resp.data

    def test_explain_with_article(self, api_client):
        src = SourceFactory()
        art = ArticleFactory(source=src)
        a = AlertFactory(metadata={"article_id": art.id})
        resp = api_client.get(f"{self.URL}{a.id}/explain/")
        assert resp.status_code == 200
        assert resp.data["trigger_data"]["article"]["id"] == art.id

    def test_explain_with_event(self, api_client):
        ev = EventFactory()
        story = StoryFactory(event=ev)
        src = SourceFactory()
        ArticleFactory(story=story, source=src)
        a = AlertFactory(metadata={"event_id": ev.id})
        resp = api_client.get(f"{self.URL}{a.id}/explain/")
        assert resp.status_code == 200
        assert resp.data["context"]["event"]["id"] == ev.id

    def test_explain_similar_alerts(self, api_client):
        key = "dedup_test_key"
        a1 = AlertFactory(dedup_key=key)
        a2 = AlertFactory(dedup_key=key)
        resp = api_client.get(f"{self.URL}{a1.id}/explain/")
        assert resp.status_code == 200
        similar_ids = [s["id"] for s in resp.data["context"]["similar_alerts"]]
        assert a2.id in similar_ids


@pytest.mark.django_db
class TestAlertLifecycle:
    URL = "/api/v1/alerts/"

    def test_acknowledge(self, auth_client):
        a = AlertFactory()
        resp = auth_client.post(f"{self.URL}{a.id}/acknowledge/", {"message": "ack"})
        assert resp.status_code == 200
        a.refresh_from_db()
        assert a.status == "acknowledged"

    def test_resolve(self, auth_client):
        a = AlertFactory()
        resp = auth_client.post(f"{self.URL}{a.id}/resolve/", {"message": "done"})
        assert resp.status_code == 200
        a.refresh_from_db()
        assert a.status == "resolved"

    def test_dismiss(self, auth_client):
        a = AlertFactory()
        resp = auth_client.post(f"{self.URL}{a.id}/dismiss/", {"message": "false positive"})
        assert resp.status_code == 200
        a.refresh_from_db()
        assert a.status == "dismissed"

    def test_escalate(self, auth_client):
        a = AlertFactory(severity="low")
        resp = auth_client.post(f"{self.URL}{a.id}/escalate/")
        assert resp.status_code == 200
        a.refresh_from_db()
        assert a.severity == "medium"

    def test_escalate_critical_fails(self, auth_client):
        a = AlertFactory(severity="critical")
        resp = auth_client.post(f"{self.URL}{a.id}/escalate/")
        assert resp.status_code == 400

    def test_comment(self, auth_client):
        a = AlertFactory()
        resp = auth_client.post(
            f"{self.URL}{a.id}/comment/",
            {"message": "Looks suspicious"},
        )
        assert resp.status_code == 200
        assert resp.data["status"] == "commented"

    def test_comment_empty_rejected(self, auth_client):
        a = AlertFactory()
        resp = auth_client.post(f"{self.URL}{a.id}/comment/", {"message": ""})
        assert resp.status_code == 400


@pytest.mark.django_db
class TestAlertStats:
    def test_stats(self, api_client):
        AlertFactory(severity="critical", status="open")
        AlertFactory(severity="low", status="open")
        AlertFactory(severity="medium", status="resolved")
        resp = api_client.get("/api/v1/alerts/stats/")
        assert resp.status_code == 200
        assert resp.data["total"] == 3
        assert resp.data["open_critical"] == 1
