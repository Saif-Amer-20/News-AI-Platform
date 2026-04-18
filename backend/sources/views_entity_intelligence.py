"""Entity Intelligence API.

Endpoints:
    GET  /api/v1/entity-intelligence/graph/          — full filtered graph (nodes + edges)
    GET  /api/v1/entity-intelligence/influence/       — top influential entities
    GET  /api/v1/entity-intelligence/emerging/        — fastest-growing entities
    GET  /api/v1/entity-intelligence/signals/         — recent entity signals feed
    POST /api/v1/entity-intelligence/signals/{id}/read/ — mark signal as read
    GET  /api/v1/entity-intelligence/relationship-types/ — available types + counts
    GET  /api/v1/entity-intelligence/dashboard/       — dashboard KPIs + summaries
    GET  /api/v1/entity-intelligence/strongest/       — top N relationships by strength
    GET  /api/v1/entity-intelligence/entities/{id}/   — single entity detail
"""
from __future__ import annotations

import logging

from django.db.models import Avg, Count, Max, Min, Q
from rest_framework.decorators import api_view
from rest_framework.response import Response

logger = logging.getLogger(__name__)


@api_view(["GET"])
def entity_graph(request):
    """Full entity co-occurrence graph, filtered and capped for visualisation.

    Query params:
      entity_type       — filter nodes (PERSON | LOCATION | ORGANIZATION)
      relationship_type — filter edges
      min_strength      — float, default 0.05
      since_days        — only include edges active in last N days
      limit_nodes       — max node count, default 80, max 200
    """
    from services.orchestration.entity_relationship_service import EntityRelationshipService

    entity_type_raw   = request.query_params.get("entity_type")
    entity_type       = entity_type_raw.lower() if entity_type_raw else None
    relationship_type = request.query_params.get("relationship_type")
    min_strength      = float(request.query_params.get("min_strength", "0.05"))
    since_days_raw    = request.query_params.get("since_days")
    since_days        = int(since_days_raw) if since_days_raw else None
    limit_nodes       = min(int(request.query_params.get("limit_nodes", "80")), 200)

    svc = EntityRelationshipService()
    graph = svc.get_entity_graph(
        entity_type=entity_type,
        relationship_type=relationship_type,
        min_strength=min_strength,
        since_days=since_days,
        limit_nodes=limit_nodes,
    )
    return Response(graph)


@api_view(["GET"])
def influence_ranking(request):
    """Top entities ranked by influence score.

    Query params:
      entity_type — filter
      limit       — default 20, max 100
    """
    from services.orchestration.entity_intelligence_service import EntityIntelligenceService

    entity_type_raw = request.query_params.get("entity_type")
    entity_type = entity_type_raw.lower() if entity_type_raw else None
    limit       = min(int(request.query_params.get("limit", "20")), 100)

    svc = EntityIntelligenceService()
    data = svc.get_most_connected(entity_type=entity_type, limit=limit)
    return Response({"results": data, "count": len(data)})


@api_view(["GET"])
def emerging_entities(request):
    """Entities with rapid recent growth in mentions.

    Query params:
      entity_type — filter
      limit       — default 20, max 100
    """
    from services.orchestration.entity_intelligence_service import EntityIntelligenceService

    entity_type_raw = request.query_params.get("entity_type")
    entity_type = entity_type_raw.lower() if entity_type_raw else None
    limit       = min(int(request.query_params.get("limit", "20")), 100)

    svc = EntityIntelligenceService()
    data = svc.get_fastest_growing(entity_type=entity_type, limit=limit)
    return Response({"results": data, "count": len(data)})


@api_view(["GET"])
def signals_feed(request):
    """Recent entity intelligence signals.

    Query params:
      signal_type   — filter by type
      severity      — low | medium | high
      unread_only   — true/false
      limit         — default 30, max 100
    """
    from sources.models import EntitySignal

    signal_type  = request.query_params.get("signal_type")
    severity     = request.query_params.get("severity")
    unread_only  = request.query_params.get("unread_only", "").lower() == "true"
    limit        = min(int(request.query_params.get("limit", "30")), 100)

    qs = EntitySignal.objects.select_related("entity", "related_entity").order_by("-created_at")

    if signal_type:
        qs = qs.filter(signal_type=signal_type)
    if severity:
        qs = qs.filter(severity=severity)
    if unread_only:
        qs = qs.filter(is_read=False)

    signals = []
    for sig in qs[:limit]:
        signals.append({
            "id":              sig.id,
            "signal_type":     sig.signal_type,
            "severity":        sig.severity,
            "title":           sig.title,
            "description":     sig.description,
            "entity_id":       sig.entity_id,
            "entity_name":     sig.entity.canonical_name or sig.entity.name,
            "entity_type":     sig.entity.entity_type,
            "related_entity_id":   sig.related_entity_id,
            "related_entity_name": (sig.related_entity.canonical_name or sig.related_entity.name) if sig.related_entity else None,
            "metadata":        sig.metadata,
            "is_read":         sig.is_read,
            "created_at":      sig.created_at.isoformat(),
            "expires_at":      sig.expires_at.isoformat() if sig.expires_at else None,
        })

    return Response({"results": signals, "count": len(signals)})


@api_view(["POST"])
def mark_signal_read(request, signal_id: int):
    """Mark an EntitySignal as read."""
    from sources.models import EntitySignal

    updated = EntitySignal.objects.filter(id=signal_id).update(is_read=True)
    if updated == 0:
        from rest_framework import status as drf_status
        return Response({"error": "Signal not found"}, status=drf_status.HTTP_404_NOT_FOUND)
    return Response({"ok": True, "signal_id": signal_id})


@api_view(["GET"])
def relationship_type_stats(request):
    """Counts of EntityRelationship rows by type (for filter UI)."""
    from sources.models import EntityRelationship

    stats = list(
        EntityRelationship.objects
        .values("relationship_type")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    total = EntityRelationship.objects.count()
    return Response({"total": total, "by_type": stats})


@api_view(["GET"])
def dashboard_summary(request):
    """Dashboard KPIs and top-level summaries for the intelligence hub.

    Returns:
      - kpis: entity count, relationship count, signal count, avg strength
      - top_influence: top 10 entities by influence score
      - top_relationships: top 10 strongest relationships
      - emerging: top 5 fastest-growing entities
      - recent_signals: last 10 meaningful signals
      - type_distribution: relationship type breakdown
    """
    from sources.models import (
        Entity, EntityInfluenceScore, EntityRelationship, EntitySignal,
    )
    from services.orchestration.entity_intelligence_service import EntityIntelligenceService
    from services.orchestration.entity_relationship_service import EntityRelationshipService

    blocked_ids = EntityRelationshipService()._build_blocked_entity_ids()

    # KPIs
    rel_agg = EntityRelationship.objects.aggregate(
        count=Count("id"),
        avg_str=Avg("strength_score"),
        max_str=Max("strength_score"),
    )
    kpis = {
        "entities": Entity.objects.count(),
        "relationships": rel_agg["count"],
        "signals": EntitySignal.objects.filter(is_read=False).count(),
        "avg_strength": round(float(rel_agg["avg_str"] or 0), 4),
        "max_strength": round(float(rel_agg["max_str"] or 0), 4),
        "scored_entities": EntityInfluenceScore.objects.count(),
    }

    # Top 10 influence
    top_influence = []
    for inf in (
        EntityInfluenceScore.objects
        .select_related("entity")
        .exclude(entity_id__in=blocked_ids)
        .order_by("influence_rank")[:10]
    ):
        e = inf.entity
        top_influence.append({
            "id": e.id,
            "name": e.canonical_name or e.name,
            "type": e.entity_type,
            "score": round(float(inf.influence_score), 4),
            "rank": inf.influence_rank,
            "mentions_7d": inf.mentions_last_7d,
            "growth_flag": inf.growth_flag,
            "degree": round(float(inf.degree_centrality), 4),
        })

    # Top 10 strongest relationships
    top_rels = []
    for rel in (
        EntityRelationship.objects
        .select_related("entity_a", "entity_b")
        .exclude(entity_a_id__in=blocked_ids)
        .exclude(entity_b_id__in=blocked_ids)
        .order_by("-strength_score")[:10]
    ):
        top_rels.append({
            "entity_a_id": rel.entity_a_id,
            "entity_a_name": rel.entity_a.canonical_name or rel.entity_a.name,
            "entity_b_id": rel.entity_b_id,
            "entity_b_name": rel.entity_b.canonical_name or rel.entity_b.name,
            "strength": round(float(rel.strength_score), 4),
            "type": rel.relationship_type,
            "co_occurrences": rel.co_occurrence_count,
            "confidence": round(float(rel.confidence), 4),
        })

    # Top 5 emerging
    svc = EntityIntelligenceService()
    emerging = svc.get_fastest_growing(limit=5)

    # Last 10 signals
    recent_signals = []
    for sig in EntitySignal.objects.select_related("entity", "related_entity").order_by("-created_at")[:10]:
        recent_signals.append({
            "id": sig.id,
            "signal_type": sig.signal_type,
            "severity": sig.severity,
            "title": sig.title,
            "description": sig.description,
            "entity_id": sig.entity_id,
            "entity_name": sig.entity.canonical_name or sig.entity.name,
            "is_read": sig.is_read,
            "created_at": sig.created_at.isoformat(),
        })

    # Type distribution
    type_dist = list(
        EntityRelationship.objects
        .values("relationship_type")
        .annotate(count=Count("id"), avg_str=Avg("strength_score"))
        .order_by("-count")
    )
    for td in type_dist:
        td["avg_str"] = round(float(td["avg_str"] or 0), 4)

    return Response({
        "kpis": kpis,
        "top_influence": top_influence,
        "top_relationships": top_rels,
        "emerging": emerging,
        "recent_signals": recent_signals,
        "type_distribution": type_dist,
    })


@api_view(["GET"])
def strongest_relationships(request):
    """Top N relationships ranked by strength.

    Query params:
      relationship_type — filter by type
      entity_type       — filter by entity type (either side)
      limit             — default 30, max 100
    """
    from sources.models import EntityRelationship
    from services.orchestration.entity_relationship_service import EntityRelationshipService

    blocked_ids = EntityRelationshipService()._build_blocked_entity_ids()

    rel_type    = request.query_params.get("relationship_type")
    entity_type = request.query_params.get("entity_type")
    limit       = min(int(request.query_params.get("limit", "30")), 100)

    qs = (
        EntityRelationship.objects
        .select_related("entity_a", "entity_b")
        .exclude(entity_a_id__in=blocked_ids)
        .exclude(entity_b_id__in=blocked_ids)
        .order_by("-strength_score")
    )
    if rel_type:
        qs = qs.filter(relationship_type=rel_type)
    if entity_type:
        qs = qs.filter(
            Q(entity_a__entity_type=entity_type)
            | Q(entity_b__entity_type=entity_type)
        )

    results = []
    for rel in qs[:limit]:
        results.append({
            "id": rel.id,
            "entity_a_id": rel.entity_a_id,
            "entity_a_name": rel.entity_a.canonical_name or rel.entity_a.name,
            "entity_a_type": rel.entity_a.entity_type,
            "entity_b_id": rel.entity_b_id,
            "entity_b_name": rel.entity_b.canonical_name or rel.entity_b.name,
            "entity_b_type": rel.entity_b.entity_type,
            "strength": round(float(rel.strength_score), 4),
            "confidence": round(float(rel.confidence), 4),
            "type": rel.relationship_type,
            "co_occurrences": rel.co_occurrence_count,
            "source_diversity": round(float(rel.source_diversity_score), 4),
            "last_seen_at": rel.last_seen_at.isoformat() if rel.last_seen_at else None,
            "growth_rate": round(float(rel.growth_rate), 4),
        })

    return Response({"results": results, "count": len(results)})


@api_view(["GET"])
def entity_detail(request, entity_id: int):
    """Detailed intelligence view for a single entity.

    Returns:
      - profile: canonical name, type, aliases, country
      - influence: score, rank, degree, velocity, mentions
      - relationships: top 20 connected entities
      - signals: recent signals for this entity
      - mention_timeline: daily mention counts over last 30 days
    """
    from datetime import timedelta

    from django.db.models import Count
    from django.db.models.functions import TruncDate
    from django.utils import timezone

    from sources.models import (
        ArticleEntity, Entity, EntityInfluenceScore,
        EntityRelationship, EntitySignal,
    )
    from services.orchestration.entity_relationship_service import EntityRelationshipService

    blocked_ids = EntityRelationshipService()._build_blocked_entity_ids()

    try:
        entity = Entity.objects.get(id=entity_id)
    except Entity.DoesNotExist:
        from rest_framework import status as drf_status
        return Response({"error": "Entity not found"}, status=drf_status.HTTP_404_NOT_FOUND)

    # Profile
    profile = {
        "id": entity.id,
        "name": entity.name,
        "canonical_name": entity.canonical_name or entity.name,
        "entity_type": entity.entity_type,
        "country": entity.country,
        "aliases": entity.aliases or [],
        "merge_confidence": float(entity.merge_confidence) if entity.merge_confidence else None,
    }

    # Influence
    inf = EntityInfluenceScore.objects.filter(entity=entity).first()
    influence_data = None
    if inf:
        influence_data = {
            "score": round(float(inf.influence_score), 4),
            "rank": inf.influence_rank,
            "degree_centrality": round(float(inf.degree_centrality), 4),
            "weighted_degree": round(float(inf.weighted_degree), 4),
            "velocity_score": round(float(inf.velocity_score), 4),
            "mentions_24h": inf.mentions_last_24h,
            "mentions_7d": inf.mentions_last_7d,
            "mentions_30d": inf.mentions_last_30d,
            "growth_flag": inf.growth_flag,
        }

    # Top 20 relationships
    rels_a = EntityRelationship.objects.filter(entity_a=entity).exclude(entity_b_id__in=blocked_ids)
    rels_b = EntityRelationship.objects.filter(entity_b=entity).exclude(entity_a_id__in=blocked_ids)
    all_rels = list(rels_a.select_related("entity_b")) + list(rels_b.select_related("entity_a"))
    all_rels.sort(key=lambda r: float(r.strength_score), reverse=True)

    relationships = []
    for rel in all_rels[:20]:
        if rel.entity_a_id == entity.id:
            other = rel.entity_b
        else:
            other = rel.entity_a
        relationships.append({
            "entity_id": other.id,
            "entity_name": other.canonical_name or other.name,
            "entity_type": other.entity_type,
            "strength": round(float(rel.strength_score), 4),
            "confidence": round(float(rel.confidence), 4),
            "type": rel.relationship_type,
            "co_occurrences": rel.co_occurrence_count,
            "last_seen_at": rel.last_seen_at.isoformat() if rel.last_seen_at else None,
        })

    # Recent signals (last 30 days)
    recent_signals = []
    for sig in (
        EntitySignal.objects
        .filter(Q(entity=entity) | Q(related_entity=entity))
        .select_related("entity", "related_entity")
        .order_by("-created_at")[:20]
    ):
        recent_signals.append({
            "id": sig.id,
            "signal_type": sig.signal_type,
            "severity": sig.severity,
            "title": sig.title,
            "description": sig.description,
            "entity_name": sig.entity.canonical_name or sig.entity.name,
            "related_entity_name": (
                (sig.related_entity.canonical_name or sig.related_entity.name)
                if sig.related_entity else None
            ),
            "is_read": sig.is_read,
            "created_at": sig.created_at.isoformat(),
        })

    # Mention timeline (daily for last 30 days)
    cutoff_30d = timezone.now() - timedelta(days=30)
    timeline = list(
        ArticleEntity.objects
        .filter(
            entity=entity,
            article__published_at__gte=cutoff_30d,
            article__is_duplicate=False,
        )
        .annotate(day=TruncDate("article__published_at"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )
    mention_timeline = [
        {"date": row["day"].isoformat(), "count": row["count"]}
        for row in timeline if row["day"]
    ]

    # Total supporting articles
    total_articles = ArticleEntity.objects.filter(
        entity=entity, article__is_duplicate=False,
    ).count()

    return Response({
        "profile": profile,
        "influence": influence_data,
        "relationships": relationships,
        "signals": recent_signals,
        "mention_timeline": mention_timeline,
        "total_articles": total_articles,
    })
