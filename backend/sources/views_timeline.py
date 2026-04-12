"""Timeline Explorer API — chronological feeds for events, entities, topics,
alerts, and case activity.

    GET /api/v1/timeline/                       — global event timeline
    GET /api/v1/timeline/entities/<id>/         — entity mention timeline
    GET /api/v1/timeline/topics/<id>/           — topic activity timeline
    GET /api/v1/timeline/alerts/                — alert timeline
    GET /api/v1/timeline/cases/<id>/            — case activity timeline
"""
from __future__ import annotations

import logging
from itertools import chain

from django.db.models import Count
from rest_framework.decorators import api_view
from rest_framework.response import Response

from sources.models import Article, Entity, Event

logger = logging.getLogger(__name__)


@api_view(["GET"])
def global_timeline(request):
    """Global event timeline feed — most recent events chronologically."""
    from_date = request.query_params.get("from_date")
    to_date = request.query_params.get("to_date")
    event_type = request.query_params.get("event_type")
    country = request.query_params.get("country")
    limit = min(int(request.query_params.get("limit", "100")), 500)

    qs = Event.objects.filter(first_reported_at__isnull=False)
    if from_date:
        qs = qs.filter(first_reported_at__gte=from_date)
    if to_date:
        qs = qs.filter(last_reported_at__lte=to_date)
    if event_type:
        qs = qs.filter(event_type=event_type)
    if country:
        qs = qs.filter(location_country=country)

    entries = []
    for e in qs.order_by("-first_reported_at")[:limit]:
        entries.append({
            "ts": e.first_reported_at.isoformat(),
            "type": "event",
            "id": e.id,
            "title": e.title,
            "event_type": e.event_type,
            "location": e.location_name,
            "country": e.location_country,
            "importance": float(e.importance_score),
            "confidence": float(e.confidence_score),
            "conflict": e.conflict_flag,
            "stories": e.story_count,
            "sources": e.source_count,
        })

    return Response({"count": len(entries), "entries": entries})


@api_view(["GET"])
def entity_timeline(request, entity_id):
    """Chronological timeline of an entity's appearances in articles and events.

    GET /api/v1/timeline/entities/<entity_id>/
    """
    try:
        entity = Entity.objects.get(id=entity_id)
    except Entity.DoesNotExist:
        return Response({"error": "Entity not found"}, status=404)

    limit = min(int(request.query_params.get("limit", "100")), 500)

    # Article mentions
    article_entries = []
    articles = (
        Article.objects.filter(
            article_entities__entity=entity,
            is_duplicate=False,
            published_at__isnull=False,
        )
        .select_related("source")
        .order_by("-published_at")[:limit]
    )
    for a in articles:
        article_entries.append({
            "ts": a.published_at.isoformat(),
            "type": "article_mention",
            "id": a.id,
            "title": a.title[:200],
            "source": a.source.name if a.source else None,
            "importance": float(a.importance_score),
        })

    # Connected events
    event_ids = (
        Article.objects.filter(
            article_entities__entity=entity,
            story__event__isnull=False,
            is_duplicate=False,
        )
        .values_list("story__event_id", flat=True)
        .distinct()[:50]
    )
    event_entries = []
    for e in Event.objects.filter(
        id__in=list(event_ids), first_reported_at__isnull=False,
    ).order_by("-first_reported_at"):
        event_entries.append({
            "ts": e.first_reported_at.isoformat(),
            "type": "event",
            "id": e.id,
            "title": e.title,
            "event_type": e.event_type,
            "importance": float(e.importance_score),
        })

    # Merge and sort chronologically
    all_entries = sorted(
        chain(article_entries, event_entries),
        key=lambda x: x["ts"],
        reverse=True,
    )[:limit]

    return Response({
        "entity_id": entity.id,
        "entity_name": entity.name,
        "count": len(all_entries),
        "entries": all_entries,
    })


@api_view(["GET"])
def topic_timeline(request, topic_id):
    """Timeline of activity for a monitored topic.

    GET /api/v1/timeline/topics/<topic_id>/
    Shows articles matching the topic + alerts triggered by the topic.
    """
    from topics.models import Topic

    try:
        topic = Topic.objects.get(id=topic_id)
    except Topic.DoesNotExist:
        return Response({"error": "Topic not found"}, status=404)

    limit = min(int(request.query_params.get("limit", "100")), 500)

    # Articles matched to this topic
    article_entries = []
    articles = (
        Article.objects.filter(
            matched_topics=topic,
            is_duplicate=False,
            published_at__isnull=False,
        )
        .select_related("source")
        .order_by("-published_at")[:limit]
    )
    for a in articles:
        article_entries.append({
            "ts": a.published_at.isoformat(),
            "type": "article_match",
            "id": a.id,
            "title": a.title[:200],
            "source": a.source.name if a.source else None,
            "matched_labels": a.matched_rule_labels or [],
            "importance": float(a.importance_score),
        })

    # Alerts triggered by this topic
    from alerts.models import Alert

    alert_entries = []
    alerts = (
        Alert.objects.filter(topic=topic)
        .order_by("-triggered_at")[:limit]
    )
    for al in alerts:
        alert_entries.append({
            "ts": al.triggered_at.isoformat() if al.triggered_at else al.created_at.isoformat(),
            "type": "alert",
            "id": al.id,
            "title": al.title,
            "alert_type": al.alert_type,
            "severity": al.severity,
            "status": al.status,
        })

    all_entries = sorted(
        chain(article_entries, alert_entries),
        key=lambda x: x["ts"],
        reverse=True,
    )[:limit]

    return Response({
        "topic_id": topic.id,
        "topic_name": topic.name,
        "count": len(all_entries),
        "entries": all_entries,
    })


@api_view(["GET"])
def alert_timeline(request):
    """Chronological alert feed.

    GET /api/v1/timeline/alerts/?severity=critical&hours=48
    """
    from datetime import timedelta

    from django.utils import timezone

    from alerts.models import Alert

    severity = request.query_params.get("severity")
    hours = int(request.query_params.get("hours", "72"))
    limit = min(int(request.query_params.get("limit", "100")), 500)

    cutoff = timezone.now() - timedelta(hours=hours)
    qs = Alert.objects.filter(triggered_at__gte=cutoff).select_related("source", "topic")

    if severity:
        qs = qs.filter(severity=severity)

    entries = []
    for al in qs.order_by("-triggered_at")[:limit]:
        entries.append({
            "ts": al.triggered_at.isoformat() if al.triggered_at else al.created_at.isoformat(),
            "type": "alert",
            "id": al.id,
            "title": al.title,
            "alert_type": al.alert_type,
            "severity": al.severity,
            "status": al.status,
            "source": al.source.name if al.source else None,
            "topic": al.topic.name if al.topic else None,
        })

    return Response({"cutoff_hours": hours, "count": len(entries), "entries": entries})


@api_view(["GET"])
def case_timeline(request, case_id):
    """Full activity timeline for a case — notes, evidence additions, status changes.

    GET /api/v1/timeline/cases/<case_id>/
    """
    from cases.models import (
        Case,
        CaseArticle,
        CaseEntity,
        CaseEvent,
        CaseMember,
        CaseNote,
        CaseReference,
    )

    try:
        case = Case.objects.get(id=case_id)
    except Case.DoesNotExist:
        return Response({"error": "Case not found"}, status=404)

    entries = []

    # Case creation
    entries.append({
        "ts": case.created_at.isoformat(),
        "type": "case_created",
        "title": f"Case created: {case.title}",
        "actor": case.owner.get_full_name() if case.owner else None,
    })

    # Notes
    for note in CaseNote.objects.filter(case=case).select_related("author"):
        entries.append({
            "ts": note.created_at.isoformat(),
            "type": f"note_{note.note_type}",
            "title": note.body[:100],
            "actor": note.author.get_full_name() if note.author else None,
            "note_id": note.id,
        })

    # Members added
    for m in CaseMember.objects.filter(case=case).select_related("user", "assigned_by"):
        entries.append({
            "ts": m.created_at.isoformat(),
            "type": "member_added",
            "title": f"Member added: {m.user.get_full_name() if m.user else 'unknown'} ({m.role})",
            "actor": m.assigned_by.get_full_name() if m.assigned_by else None,
        })

    # Articles linked
    for ca in CaseArticle.objects.filter(case=case).select_related("article", "added_by"):
        entries.append({
            "ts": ca.created_at.isoformat(),
            "type": "article_linked",
            "title": f"Article linked: {ca.article.title[:80]}",
            "object_id": ca.article.id,
            "actor": ca.added_by.get_full_name() if ca.added_by else None,
        })

    # Entities linked
    for ce in CaseEntity.objects.filter(case=case).select_related("entity", "added_by"):
        entries.append({
            "ts": ce.created_at.isoformat(),
            "type": "entity_linked",
            "title": f"Entity linked: {ce.entity.name}",
            "object_id": ce.entity.id,
            "actor": ce.added_by.get_full_name() if ce.added_by else None,
        })

    # Events linked
    for cev in CaseEvent.objects.filter(case=case).select_related("event", "added_by"):
        entries.append({
            "ts": cev.created_at.isoformat(),
            "type": "event_linked",
            "title": f"Event linked: {cev.event.title}",
            "object_id": cev.event.id,
            "actor": cev.added_by.get_full_name() if cev.added_by else None,
        })

    # References
    for ref in CaseReference.objects.filter(case=case).select_related("added_by"):
        entries.append({
            "ts": ref.created_at.isoformat(),
            "type": "reference_added",
            "title": f"Reference: {ref.title}",
            "reference_type": ref.reference_type,
            "actor": ref.added_by.get_full_name() if ref.added_by else None,
        })

    # Case closed
    if case.closed_at:
        entries.append({
            "ts": case.closed_at.isoformat(),
            "type": "case_closed",
            "title": "Case closed",
        })

    # Sort chronologically (newest first)
    entries.sort(key=lambda x: x["ts"], reverse=True)

    return Response({
        "case_id": case.id,
        "case_title": case.title,
        "count": len(entries),
        "entries": entries,
    })
