"""Tests for Case workspace API endpoints."""
from __future__ import annotations

import pytest

from conftest import (
    ArticleFactory,
    CaseFactory,
    EntityFactory,
    EventFactory,
    SavedSearchFactory,
    SourceFactory,
    UserFactory,
)


@pytest.mark.django_db
class TestCaseCRUD:
    URL = "/api/v1/cases/"

    def test_list(self, auth_client, case):
        resp = auth_client.get(self.URL)
        assert resp.status_code == 200
        assert resp.data["count"] >= 1

    def test_create(self, auth_client):
        resp = auth_client.post(self.URL, {
            "title": "New Case",
            "description": "Investigation into XYZ",
            "priority": "high",
        })
        assert resp.status_code == 201
        assert resp.data["title"] == "New Case"

    def test_detail(self, auth_client, case):
        resp = auth_client.get(f"{self.URL}{case.id}/")
        assert resp.status_code == 200
        assert resp.data["title"] == case.title

    def test_update(self, auth_client, case):
        resp = auth_client.patch(
            f"{self.URL}{case.id}/",
            {"description": "Updated description"},
            format="json",
        )
        assert resp.status_code == 200
        case.refresh_from_db()
        assert case.description == "Updated description"

    def test_filter_by_status(self, auth_client, user):
        CaseFactory(owner=user, created_by=user, status="open")
        CaseFactory(owner=user, created_by=user, status="closed")
        resp = auth_client.get(self.URL, {"status": "open"})
        assert resp.data["count"] == 1


@pytest.mark.django_db
class TestCaseLifecycle:
    URL = "/api/v1/cases/"

    def test_close(self, auth_client, case):
        resp = auth_client.post(f"{self.URL}{case.id}/close/")
        assert resp.status_code == 200
        case.refresh_from_db()
        assert case.status == "closed"
        assert case.closed_at is not None

    def test_reopen(self, auth_client, case):
        case.status = "closed"
        case.save()
        resp = auth_client.post(f"{self.URL}{case.id}/reopen/")
        assert resp.status_code == 200
        case.refresh_from_db()
        assert case.status == "open"
        assert case.closed_at is None


@pytest.mark.django_db
class TestCaseMembers:
    URL = "/api/v1/cases/"

    def test_list_members(self, auth_client, case):
        resp = auth_client.get(f"{self.URL}{case.id}/members/")
        assert resp.status_code == 200

    def test_add_member(self, auth_client, case):
        new_user = UserFactory()
        resp = auth_client.post(
            f"{self.URL}{case.id}/members/",
            {"user": new_user.id, "role": "analyst"},
        )
        assert resp.status_code == 201


@pytest.mark.django_db
class TestCaseNotes:
    URL = "/api/v1/cases/"

    def test_list_notes(self, auth_client, case):
        resp = auth_client.get(f"{self.URL}{case.id}/notes/")
        assert resp.status_code == 200

    def test_add_note(self, auth_client, case):
        resp = auth_client.post(
            f"{self.URL}{case.id}/notes/",
            {"note_type": "analyst_note", "body": "Important finding."},
        )
        assert resp.status_code == 201


@pytest.mark.django_db
class TestCaseReferences:
    URL = "/api/v1/cases/"

    def test_list_references(self, auth_client, case):
        resp = auth_client.get(f"{self.URL}{case.id}/references/")
        assert resp.status_code == 200

    def test_add_reference(self, auth_client, case):
        resp = auth_client.post(
            f"{self.URL}{case.id}/references/",
            {
                "reference_type": "external",
                "title": "OSINT Report",
                "external_url": "https://example.com/report",
            },
        )
        assert resp.status_code == 201


@pytest.mark.django_db
class TestCaseInvestigation:
    URL = "/api/v1/cases/"

    def test_add_article(self, auth_client, case):
        art = ArticleFactory(source=SourceFactory())
        resp = auth_client.post(
            f"{self.URL}{case.id}/add-article/",
            {"article": art.id, "relevance": "high"},
        )
        assert resp.status_code == 201

    def test_remove_article(self, auth_client, case):
        from cases.models import CaseArticle
        art = ArticleFactory(source=SourceFactory())
        CaseArticle.objects.create(case=case, article=art)
        resp = auth_client.delete(f"{self.URL}{case.id}/remove-article/{art.id}/")
        assert resp.status_code == 204

    def test_add_entity(self, auth_client, case):
        ent = EntityFactory()
        resp = auth_client.post(
            f"{self.URL}{case.id}/add-entity/",
            {"entity": ent.id},
        )
        assert resp.status_code == 201

    def test_add_event(self, auth_client, case):
        ev = EventFactory()
        resp = auth_client.post(
            f"{self.URL}{case.id}/add-event/",
            {"event": ev.id},
        )
        assert resp.status_code == 201

    def test_summary(self, auth_client, case):
        art = ArticleFactory(source=SourceFactory())
        ent = EntityFactory()
        ev = EventFactory()
        from cases.models import CaseArticle, CaseEntity, CaseEvent
        CaseArticle.objects.create(case=case, article=art)
        CaseEntity.objects.create(case=case, entity=ent)
        CaseEvent.objects.create(case=case, event=ev)
        resp = auth_client.get(f"{self.URL}{case.id}/summary/")
        assert resp.status_code == 200
        assert resp.data["article_count"] == 1
        assert resp.data["entity_count"] == 1
        assert resp.data["event_count"] == 1


@pytest.mark.django_db
class TestSavedSearchCRUD:
    URL = "/api/v1/saved-searches/"

    def test_list(self, auth_client, user):
        SavedSearchFactory(owner=user)
        SavedSearchFactory(is_global=True)
        resp = auth_client.get(self.URL)
        assert resp.status_code == 200
        # own + global
        assert resp.data["count"] == 2

    def test_create(self, auth_client):
        resp = auth_client.post(self.URL, {
            "name": "My Search",
            "search_type": "article",
            "query_params": {"q": "explosion"},
        }, format="json")
        assert resp.status_code == 201
        assert resp.data["name"] == "My Search"

    def test_filter_global(self, auth_client, user):
        SavedSearchFactory(owner=user, is_global=False)
        SavedSearchFactory(is_global=True)
        resp = auth_client.get(self.URL, {"global": "true"})
        assert resp.data["count"] == 1
