"""Case workspace API — full CRUD + investigation workflow.

Endpoints:
    GET/POST         /api/v1/cases/                     — list / create
    GET/PATCH/DELETE  /api/v1/cases/{id}/                — detail / update / delete
    POST              /api/v1/cases/{id}/close/          — close case
    POST              /api/v1/cases/{id}/reopen/         — reopen case
    GET/POST          /api/v1/cases/{id}/members/        — list / add members
    DELETE            /api/v1/cases/{id}/members/{mid}/  — remove member
    GET/POST          /api/v1/cases/{id}/notes/          — list / add notes
    PATCH             /api/v1/cases/{id}/notes/{nid}/    — update note
    GET/POST          /api/v1/cases/{id}/references/     — list / add references
    POST              /api/v1/cases/{id}/add-article/    — link article to case
    POST              /api/v1/cases/{id}/add-entity/     — link entity to case
    POST              /api/v1/cases/{id}/add-event/      — link event to case
    DELETE            /api/v1/cases/{id}/remove-article/{aid}/
    GET               /api/v1/cases/{id}/summary/        — investigation summary

    GET/POST          /api/v1/saved-searches/            — list / create
    GET/PATCH/DELETE  /api/v1/saved-searches/{id}/       — detail / update / delete
    POST              /api/v1/saved-searches/{id}/execute/ — re-execute
"""
from __future__ import annotations

from django.db.models import Count
from django.utils import timezone
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import (
    Case,
    CaseArticle,
    CaseEntity,
    CaseEvent,
    CaseMember,
    CaseNote,
    CaseReference,
    SavedSearch,
)
from .serializers import (
    CaseArticleSerializer,
    CaseCreateSerializer,
    CaseDetailSerializer,
    CaseEntitySerializer,
    CaseEventSerializer,
    CaseListSerializer,
    CaseMemberSerializer,
    CaseNoteSerializer,
    CaseReferenceSerializer,
    SavedSearchSerializer,
)


class CaseViewSet(viewsets.ModelViewSet):
    """Full case workspace CRUD + investigation workflow."""

    queryset = (
        Case.objects.annotate(
            article_count=Count("articles", distinct=True),
            member_count=Count("members", distinct=True),
        )
        .select_related("owner")
        .order_by("-updated_at")
    )
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["title", "description"]
    ordering_fields = ["priority", "status", "updated_at", "opened_at", "due_at"]
    ordering = ["-updated_at"]

    def get_serializer_class(self):
        if self.action == "create":
            return CaseCreateSerializer
        if self.action in ("retrieve", "update", "partial_update"):
            return CaseDetailSerializer
        return CaseListSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        case_status = self.request.query_params.get("status")
        priority = self.request.query_params.get("priority")
        classification = self.request.query_params.get("classification")
        owner = self.request.query_params.get("owner")

        if case_status:
            qs = qs.filter(status=case_status)
        if priority:
            qs = qs.filter(priority=priority)
        if classification:
            qs = qs.filter(classification=classification)
        if owner:
            qs = qs.filter(owner_id=owner)
        return qs

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(owner=user, created_by=user)

    def perform_update(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(updated_by=user)

    # ── Lifecycle ──────────────────────────────────────────────────

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        case = self.get_object()
        case.status = Case.Status.CLOSED
        case.closed_at = timezone.now()
        case.updated_by = request.user if request.user.is_authenticated else None
        case.save(update_fields=["status", "closed_at", "updated_by", "updated_at"])
        return Response({"status": "closed"})

    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        case = self.get_object()
        case.status = Case.Status.OPEN
        case.closed_at = None
        case.updated_by = request.user if request.user.is_authenticated else None
        case.save(update_fields=["status", "closed_at", "updated_by", "updated_at"])
        return Response({"status": "reopened"})

    # ── Members ────────────────────────────────────────────────────

    @action(detail=True, methods=["get", "post"])
    def members(self, request, pk=None):
        case = self.get_object()
        if request.method == "GET":
            members = CaseMember.objects.filter(case=case).select_related("user")
            serializer = CaseMemberSerializer(members, many=True)
            return Response(serializer.data)

        serializer = CaseMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(
            case=case,
            assigned_by=request.user if request.user.is_authenticated else None,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["delete"], url_path=r"members/(?P<member_id>\d+)")
    def remove_member(self, request, pk=None, member_id=None):
        case = self.get_object()
        CaseMember.objects.filter(case=case, id=member_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ── Notes ──────────────────────────────────────────────────────

    @action(detail=True, methods=["get", "post"])
    def notes(self, request, pk=None):
        case = self.get_object()
        if request.method == "GET":
            notes = CaseNote.objects.filter(case=case).select_related("author")
            serializer = CaseNoteSerializer(notes, many=True)
            return Response(serializer.data)

        serializer = CaseNoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(
            case=case,
            author=request.user if request.user.is_authenticated else None,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["patch"], url_path=r"notes/(?P<note_id>\d+)")
    def update_note(self, request, pk=None, note_id=None):
        case = self.get_object()
        try:
            note = CaseNote.objects.get(case=case, id=note_id)
        except CaseNote.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        serializer = CaseNoteSerializer(note, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    # ── References ─────────────────────────────────────────────────

    @action(detail=True, methods=["get", "post"])
    def references(self, request, pk=None):
        case = self.get_object()
        if request.method == "GET":
            refs = CaseReference.objects.filter(case=case)
            serializer = CaseReferenceSerializer(refs, many=True)
            return Response(serializer.data)

        serializer = CaseReferenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(
            case=case,
            added_by=request.user if request.user.is_authenticated else None,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    # ── Investigation: Link articles/entities/events ───────────────

    @action(detail=True, methods=["post"], url_path="add-article")
    def add_article(self, request, pk=None):
        case = self.get_object()
        serializer = CaseArticleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(
            case=case,
            added_by=request.user if request.user.is_authenticated else None,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["delete"], url_path=r"remove-article/(?P<article_id>\d+)")
    def remove_article(self, request, pk=None, article_id=None):
        case = self.get_object()
        CaseArticle.objects.filter(case=case, article_id=article_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="add-entity")
    def add_entity(self, request, pk=None):
        case = self.get_object()
        serializer = CaseEntitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(
            case=case,
            added_by=request.user if request.user.is_authenticated else None,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["delete"], url_path=r"remove-entity/(?P<entity_id>\d+)")
    def remove_entity(self, request, pk=None, entity_id=None):
        case = self.get_object()
        CaseEntity.objects.filter(case=case, entity_id=entity_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="add-event")
    def add_event(self, request, pk=None):
        case = self.get_object()
        serializer = CaseEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(
            case=case,
            added_by=request.user if request.user.is_authenticated else None,
        )
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["delete"], url_path=r"remove-event/(?P<event_id>\d+)")
    def remove_event(self, request, pk=None, event_id=None):
        case = self.get_object()
        CaseEvent.objects.filter(case=case, event_id=event_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ── Investigation summary ──────────────────────────────────────

    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        """Aggregate summary of all evidence linked to a case."""
        case = self.get_object()

        articles = CaseArticle.objects.filter(case=case).select_related("article__source")
        entities = CaseEntity.objects.filter(case=case).select_related("entity")
        events = CaseEvent.objects.filter(case=case).select_related("event")

        source_breakdown = {}
        for ca in articles:
            src = ca.article.source.name if ca.article.source else "Unknown"
            source_breakdown[src] = source_breakdown.get(src, 0) + 1

        entity_type_breakdown = {}
        for ce in entities:
            et = ce.entity.entity_type
            entity_type_breakdown[et] = entity_type_breakdown.get(et, 0) + 1

        event_type_breakdown = {}
        for cev in events:
            evtype = cev.event.event_type
            event_type_breakdown[evtype] = event_type_breakdown.get(evtype, 0) + 1

        return Response({
            "case_id": case.id,
            "title": case.title,
            "status": case.status,
            "article_count": articles.count(),
            "entity_count": entities.count(),
            "event_count": events.count(),
            "note_count": CaseNote.objects.filter(case=case).count(),
            "member_count": CaseMember.objects.filter(case=case).count(),
            "source_breakdown": source_breakdown,
            "entity_type_breakdown": entity_type_breakdown,
            "event_type_breakdown": event_type_breakdown,
        })

    # ── Timeline ───────────────────────────────────────────────────

    @action(detail=True, methods=["get"])
    def timeline(self, request, pk=None):
        """Full activity timeline for this case — all actions chronologically."""
        case = self.get_object()
        entries = []

        # Case creation
        entries.append({
            "ts": case.created_at.isoformat(),
            "type": "case_created",
            "detail": f"Case created: {case.title}",
            "actor": case.owner.get_full_name() if case.owner else None,
        })

        # Notes
        for note in CaseNote.objects.filter(case=case).select_related("author"):
            entries.append({
                "ts": note.created_at.isoformat(),
                "type": f"note_{note.note_type}",
                "detail": note.body[:150],
                "object_id": note.id,
                "actor": note.author.get_full_name() if note.author else None,
            })

        # Members
        for m in CaseMember.objects.filter(case=case).select_related("user", "assigned_by"):
            entries.append({
                "ts": m.created_at.isoformat(),
                "type": "member_added",
                "detail": f"{m.user.get_full_name() if m.user else 'unknown'} added as {m.role}",
                "actor": m.assigned_by.get_full_name() if m.assigned_by else None,
            })

        # Articles
        for ca in CaseArticle.objects.filter(case=case).select_related("article", "added_by"):
            entries.append({
                "ts": ca.created_at.isoformat(),
                "type": "article_linked",
                "detail": ca.article.title[:100],
                "object_id": ca.article.id,
                "actor": ca.added_by.get_full_name() if ca.added_by else None,
            })

        # Entities
        for ce in CaseEntity.objects.filter(case=case).select_related("entity", "added_by"):
            entries.append({
                "ts": ce.created_at.isoformat(),
                "type": "entity_linked",
                "detail": ce.entity.name,
                "object_id": ce.entity.id,
                "actor": ce.added_by.get_full_name() if ce.added_by else None,
            })

        # Events
        for cev in CaseEvent.objects.filter(case=case).select_related("event", "added_by"):
            entries.append({
                "ts": cev.created_at.isoformat(),
                "type": "event_linked",
                "detail": cev.event.title,
                "object_id": cev.event.id,
                "actor": cev.added_by.get_full_name() if cev.added_by else None,
            })

        # References
        for ref in CaseReference.objects.filter(case=case).select_related("added_by"):
            entries.append({
                "ts": ref.created_at.isoformat(),
                "type": "reference_added",
                "detail": ref.title,
                "reference_type": ref.reference_type,
                "actor": ref.added_by.get_full_name() if ref.added_by else None,
            })

        if case.closed_at:
            entries.append({
                "ts": case.closed_at.isoformat(),
                "type": "case_closed",
                "detail": "Case closed",
            })

        entries.sort(key=lambda x: x["ts"], reverse=True)
        return Response({
            "case_id": case.id,
            "count": len(entries),
            "entries": entries,
        })

    # ── Export ──────────────────────────────────────────────────────

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        """Export full case data as a structured JSON document.

        Includes all metadata, members, notes, evidence, and references.
        """
        case = self.get_object()

        articles = CaseArticle.objects.filter(case=case).select_related(
            "article__source", "added_by",
        )
        entities = CaseEntity.objects.filter(case=case).select_related(
            "entity", "added_by",
        )
        events = CaseEvent.objects.filter(case=case).select_related(
            "event", "added_by",
        )
        notes = CaseNote.objects.filter(case=case).select_related("author")
        members = CaseMember.objects.filter(case=case).select_related("user", "assigned_by")
        references = CaseReference.objects.filter(case=case).select_related("added_by")

        export_data = {
            "export_format": "newsintel_case_v1",
            "exported_at": timezone.now().isoformat(),
            "case": {
                "id": case.id,
                "title": case.title,
                "slug": case.slug,
                "description": case.description,
                "status": case.status,
                "priority": case.priority,
                "classification": case.classification,
                "owner": case.owner.get_full_name() if case.owner else None,
                "opened_at": case.opened_at.isoformat() if case.opened_at else None,
                "closed_at": case.closed_at.isoformat() if case.closed_at else None,
                "due_at": case.due_at.isoformat() if case.due_at else None,
                "metadata": case.metadata,
            },
            "members": [
                {
                    "user": m.user.get_full_name() if m.user else None,
                    "role": m.role,
                    "assigned_by": m.assigned_by.get_full_name() if m.assigned_by else None,
                    "added_at": m.created_at.isoformat(),
                }
                for m in members
            ],
            "notes": [
                {
                    "id": n.id,
                    "note_type": n.note_type,
                    "body": n.body,
                    "is_pinned": n.is_pinned,
                    "author": n.author.get_full_name() if n.author else None,
                    "created_at": n.created_at.isoformat(),
                }
                for n in notes
            ],
            "articles": [
                {
                    "article_id": ca.article.id,
                    "title": ca.article.title,
                    "url": ca.article.url,
                    "source": ca.article.source.name if ca.article.source else None,
                    "relevance": ca.relevance,
                    "notes": ca.notes,
                    "added_by": ca.added_by.get_full_name() if ca.added_by else None,
                    "added_at": ca.created_at.isoformat(),
                }
                for ca in articles
            ],
            "entities": [
                {
                    "entity_id": ce.entity.id,
                    "name": ce.entity.name,
                    "entity_type": ce.entity.entity_type,
                    "country": ce.entity.country,
                    "notes": ce.notes,
                    "added_by": ce.added_by.get_full_name() if ce.added_by else None,
                    "added_at": ce.created_at.isoformat(),
                }
                for ce in entities
            ],
            "events": [
                {
                    "event_id": cev.event.id,
                    "title": cev.event.title,
                    "event_type": cev.event.event_type,
                    "location": cev.event.location_name,
                    "country": cev.event.location_country,
                    "notes": cev.notes,
                    "added_by": cev.added_by.get_full_name() if cev.added_by else None,
                    "added_at": cev.created_at.isoformat(),
                }
                for cev in events
            ],
            "references": [
                {
                    "id": ref.id,
                    "reference_type": ref.reference_type,
                    "title": ref.title,
                    "external_url": ref.external_url,
                    "metadata": ref.metadata,
                    "added_by": ref.added_by.get_full_name() if ref.added_by else None,
                    "added_at": ref.created_at.isoformat(),
                }
                for ref in references
            ],
        }

        return Response(export_data)


class SavedSearchViewSet(viewsets.ModelViewSet):
    """Saved search / filter management.

    GET/POST  /api/v1/saved-searches/               — list / create
    GET/PATCH /api/v1/saved-searches/{id}/           — detail / update
    DELETE    /api/v1/saved-searches/{id}/           — delete
    POST      /api/v1/saved-searches/{id}/execute/   — re-execute search
    """

    queryset = SavedSearch.objects.select_related("owner", "case").order_by("-updated_at")
    serializer_class = SavedSearchSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "description"]
    ordering_fields = ["name", "search_type", "execution_count", "updated_at"]

    def get_queryset(self):
        qs = super().get_queryset()
        search_type = self.request.query_params.get("search_type")
        case_id = self.request.query_params.get("case")
        global_only = self.request.query_params.get("global")

        if search_type:
            qs = qs.filter(search_type=search_type)
        if case_id:
            qs = qs.filter(case_id=case_id)
        if global_only and global_only.lower() in ("true", "1"):
            qs = qs.filter(is_global=True)

        # Show own searches + global ones
        user = self.request.user
        if user.is_authenticated:
            from django.db.models import Q
            qs = qs.filter(Q(owner=user) | Q(is_global=True))
        else:
            qs = qs.filter(is_global=True)
        return qs

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(owner=user)

    @action(detail=True, methods=["post"])
    def execute(self, request, pk=None):
        """Re-execute a saved search and return results.

        Delegates to OpenSearch for article/event searches,
        or uses Django ORM for entity/alert searches.
        """
        saved = self.get_object()
        params = saved.query_params or {}
        saved.last_executed_at = timezone.now()
        saved.execution_count = (saved.execution_count or 0) + 1
        saved.save(update_fields=["last_executed_at", "execution_count", "updated_at"])

        if saved.search_type == SavedSearch.SearchType.ARTICLE:
            return self._execute_article_search(params)
        elif saved.search_type == SavedSearch.SearchType.EVENT:
            return self._execute_event_search(params)
        elif saved.search_type == SavedSearch.SearchType.ENTITY:
            return self._execute_entity_search(params)
        elif saved.search_type == SavedSearch.SearchType.ALERT:
            return self._execute_alert_search(params)
        return Response({"error": "Unknown search type"}, status=status.HTTP_400_BAD_REQUEST)

    def _execute_article_search(self, params: dict) -> Response:
        q = params.get("q", "")
        from services.orchestration.opensearch_service import OpenSearchService
        try:
            svc = OpenSearchService()
            results = svc.search_articles(
                q,
                source_name=params.get("source"),
                event_type=params.get("event_type"),
                min_quality=float(params["min_quality"]) if params.get("min_quality") else None,
                min_importance=float(params["min_importance"]) if params.get("min_importance") else None,
                from_date=params.get("from_date"),
                to_date=params.get("to_date"),
                size=min(int(params.get("size", 20)), 100),
            )
        except Exception:
            return Response({"error": "Search unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"query": q, "count": len(results), "results": results})

    def _execute_event_search(self, params: dict) -> Response:
        q = params.get("q", "")
        from services.orchestration.opensearch_service import OpenSearchService
        try:
            svc = OpenSearchService()
            results = svc.search_events(
                q,
                event_type=params.get("event_type"),
                country=params.get("country"),
                conflict_only=params.get("conflict", "").lower() in ("true", "1"),
                min_confidence=float(params["min_confidence"]) if params.get("min_confidence") else None,
                size=min(int(params.get("size", 20)), 100),
            )
        except Exception:
            return Response({"error": "Search unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"query": q, "count": len(results), "results": results})

    def _execute_entity_search(self, params: dict) -> Response:
        from django.db.models import Q, Count
        from sources.models import Entity
        qs = Entity.objects.annotate(article_count=Count("article_entities"))
        q = params.get("q", "")
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(canonical_name__icontains=q))
        if params.get("entity_type"):
            qs = qs.filter(entity_type=params["entity_type"])
        if params.get("country"):
            qs = qs.filter(country=params["country"])
        qs = qs.order_by("-article_count")[:int(params.get("size", 20))]
        from sources.serializers import EntitySerializer
        return Response(EntitySerializer(qs, many=True).data)

    def _execute_alert_search(self, params: dict) -> Response:
        from alerts.models import Alert
        from alerts.serializers import AlertListSerializer
        qs = Alert.objects.select_related("source", "topic")
        if params.get("alert_type"):
            qs = qs.filter(alert_type=params["alert_type"])
        if params.get("severity"):
            qs = qs.filter(severity=params["severity"])
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        qs = qs.order_by("-triggered_at")[:int(params.get("size", 20))]
        return Response(AlertListSerializer(qs, many=True).data)
