"""Dashboard / Command Center API.

Provides high-level situational awareness in a single screen:
    GET /api/v1/dashboard/overview/             — platform-wide stats snapshot
    GET /api/v1/dashboard/high-priority-events/ — top events by importance
    GET /api/v1/dashboard/watchlist-hits/        — recent watchlist keyword matches
    GET /api/v1/dashboard/conflict-events/      — events with narrative conflicts
    GET /api/v1/dashboard/recent-alerts/        — latest alert feed
    GET /api/v1/dashboard/source-health/        — source reliability overview
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from alerts.models import Alert
from cases.models import Case
from sources.models import Article, Entity, Event, Source, Story


@api_view(["GET"])
def dashboard_overview(request):
    """Platform-wide stats snapshot for the analyst command center."""
    now = timezone.now()
    last_24h = now - timedelta(hours=24)
    last_7d = now - timedelta(days=7)

    # Event stats
    total_events = Event.objects.count()
    events_24h = Event.objects.filter(first_reported_at__gte=last_24h).count()
    events_7d = Event.objects.filter(first_reported_at__gte=last_7d).count()
    conflict_events = Event.objects.filter(conflict_flag=True).count()
    high_importance_events = Event.objects.filter(importance_score__gte=0.7).count()

    # Article stats
    total_articles = Article.objects.filter(is_duplicate=False).count()
    articles_24h = Article.objects.filter(
        is_duplicate=False, created_at__gte=last_24h,
    ).count()

    # Source stats
    active_sources = Source.objects.filter(is_active=True).count()
    unhealthy_sources = Source.objects.filter(
        is_active=True, health_status__in=["degraded", "failing"],
    ).count()
    avg_trust = Source.objects.filter(is_active=True).aggregate(
        avg=Avg("trust_score"),
    )["avg"]

    # Alert stats
    open_alerts = Alert.objects.filter(
        status__in=[Alert.Status.OPEN, Alert.Status.ACKNOWLEDGED],
    ).count()
    critical_alerts = Alert.objects.filter(
        status=Alert.Status.OPEN, severity=Alert.Severity.CRITICAL,
    ).count()
    alerts_24h = Alert.objects.filter(triggered_at__gte=last_24h).count()

    # Case stats
    open_cases = Case.objects.filter(
        status__in=[Case.Status.OPEN, Case.Status.ON_HOLD],
    ).count()

    # Entity stats
    total_entities = Entity.objects.count()

    # Story stats
    total_stories = Story.objects.count()
    stories_24h = Story.objects.filter(created_at__gte=last_24h).count()

    return Response({
        "generated_at": now.isoformat(),
        "events": {
            "total": total_events,
            "last_24h": events_24h,
            "last_7d": events_7d,
            "conflicts": conflict_events,
            "high_importance": high_importance_events,
        },
        "articles": {
            "total": total_articles,
            "last_24h": articles_24h,
        },
        "stories": {
            "total": total_stories,
            "last_24h": stories_24h,
        },
        "sources": {
            "active": active_sources,
            "unhealthy": unhealthy_sources,
            "avg_trust_score": round(float(avg_trust or 0), 3),
        },
        "alerts": {
            "open": open_alerts,
            "critical": critical_alerts,
            "last_24h": alerts_24h,
        },
        "cases": {
            "open": open_cases,
        },
        "entities": {
            "total": total_entities,
        },
    })


@api_view(["GET"])
def high_priority_events(request):
    """Top events by importance + recency, weighted for analyst attention."""
    limit = min(int(request.query_params.get("limit", "20")), 100)
    hours = int(request.query_params.get("hours", "72"))
    cutoff = timezone.now() - timedelta(hours=hours)

    events = (
        Event.objects.filter(first_reported_at__gte=cutoff)
        .order_by("-importance_score", "-source_count", "-last_reported_at")
        .values(
            "id", "title", "event_type", "location_name", "location_country",
            "importance_score", "confidence_score", "conflict_flag",
            "story_count", "source_count",
            "first_reported_at", "last_reported_at",
        )[:limit]
    )

    return Response({
        "cutoff_hours": hours,
        "count": len(events),
        "events": list(events),
    })


@api_view(["GET"])
def watchlist_hits(request):
    """Recent articles that matched watchlist keyword rules."""
    limit = min(int(request.query_params.get("limit", "30")), 100)
    hours = int(request.query_params.get("hours", "48"))
    cutoff = timezone.now() - timedelta(hours=hours)

    articles = (
        Article.objects.filter(
            is_duplicate=False,
            matched_topics__isnull=False,
            created_at__gte=cutoff,
        )
        .select_related("source")
        .distinct()
        .order_by("-importance_score", "-created_at")[:limit]
    )

    results = []
    for a in articles:
        topic_names = list(a.matched_topics.values_list("name", flat=True))
        results.append({
            "article_id": a.id,
            "title": a.title[:200],
            "url": a.url,
            "source": a.source.name if a.source else None,
            "matched_topics": topic_names,
            "matched_labels": a.matched_rule_labels or [],
            "importance_score": float(a.importance_score),
            "quality_score": float(a.quality_score),
            "published_at": a.published_at.isoformat() if a.published_at else None,
        })

    return Response({
        "cutoff_hours": hours,
        "count": len(results),
        "hits": results,
    })


@api_view(["GET"])
def conflict_events(request):
    """Events with detected narrative conflicts between sources."""
    limit = min(int(request.query_params.get("limit", "30")), 100)

    events = (
        Event.objects.filter(conflict_flag=True)
        .order_by("-importance_score", "-last_reported_at")
        .values(
            "id", "title", "event_type", "description",
            "location_name", "location_country",
            "importance_score", "confidence_score",
            "story_count", "source_count",
            "first_reported_at", "last_reported_at",
        )[:limit]
    )

    results = []
    for e in events:
        # Fetch narrative_conflicts from metadata
        event_obj = Event.objects.only("metadata", "narrative_conflicts").get(id=e["id"])
        conflicts_data = event_obj.narrative_conflicts or []
        e["narrative_conflicts"] = conflicts_data[:5]  # Top 5 conflicts
        results.append(e)

    return Response({
        "count": len(results),
        "events": results,
    })


@api_view(["GET"])
def recent_alerts(request):
    """Latest alerts feed for the dashboard."""
    limit = min(int(request.query_params.get("limit", "20")), 100)
    severity = request.query_params.get("severity")
    status_filter = request.query_params.get("status")

    qs = Alert.objects.select_related("source", "topic").order_by("-triggered_at")

    if severity:
        qs = qs.filter(severity=severity)
    if status_filter:
        qs = qs.filter(status=status_filter)
    else:
        # Default: show open + acknowledged
        qs = qs.filter(status__in=[Alert.Status.OPEN, Alert.Status.ACKNOWLEDGED])

    alerts = qs.values(
        "id", "title", "alert_type", "severity", "status",
        "summary", "source__name", "topic__name", "triggered_at",
    )[:limit]

    return Response({
        "count": len(alerts),
        "alerts": list(alerts),
    })


@api_view(["GET"])
def source_health(request):
    """Source reliability overview for the dashboard."""
    sources = (
        Source.objects.filter(is_active=True)
        .values(
            "id", "name", "source_type", "country", "trust_score",
            "health_status", "status", "total_articles_fetched",
            "avg_quality_score", "last_checked_at", "last_success_at",
            "last_failure_at",
        )
        .order_by("health_status", "trust_score")
    )

    # Aggregate by health status
    health_summary = {}
    for s in sources:
        hs = s["health_status"] or "unknown"
        if hs not in health_summary:
            health_summary[hs] = 0
        health_summary[hs] += 1

    return Response({
        "health_summary": health_summary,
        "sources": list(sources),
    })
