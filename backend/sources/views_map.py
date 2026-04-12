"""Map Explorer API — geo-located events, entities, alerts, heatmaps, clusters.

    GET /api/v1/map/events/     — geo-located events as GeoJSON
    GET /api/v1/map/entities/   — geo-located entities as GeoJSON
    GET /api/v1/map/alerts/     — geo-located alerts as GeoJSON
    GET /api/v1/map/heat/       — heatmap weight data
    GET /api/v1/map/clusters/   — clustered events by proximity
"""
from __future__ import annotations

import logging
from collections import defaultdict

from django.db.models import Avg, Count, Q
from rest_framework.decorators import api_view
from rest_framework.response import Response

from sources.models import Article, Entity, Event

logger = logging.getLogger(__name__)


@api_view(["GET"])
def map_events(request):
    """Return geo-located events as GeoJSON FeatureCollection."""
    qs = Event.objects.filter(
        location_lat__isnull=False,
        location_lon__isnull=False,
    )

    event_type = request.query_params.get("event_type")
    country = request.query_params.get("country")
    from_date = request.query_params.get("from_date")
    to_date = request.query_params.get("to_date")
    conflict = request.query_params.get("conflict")
    min_importance = request.query_params.get("min_importance")

    if event_type:
        qs = qs.filter(event_type=event_type)
    if country:
        qs = qs.filter(location_country=country)
    if from_date:
        qs = qs.filter(first_reported_at__gte=from_date)
    if to_date:
        qs = qs.filter(last_reported_at__lte=to_date)
    if conflict and conflict.lower() in ("true", "1"):
        qs = qs.filter(conflict_flag=True)
    if min_importance:
        qs = qs.filter(importance_score__gte=min_importance)

    events = qs.values(
        "id", "title", "event_type", "location_name", "location_country",
        "location_lat", "location_lon", "importance_score", "confidence_score",
        "conflict_flag", "story_count", "source_count",
        "first_reported_at", "last_reported_at",
    ).order_by("-last_reported_at")[:500]

    features = []
    for e in events:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(e["location_lon"]), float(e["location_lat"])],
            },
            "properties": {
                "id": e["id"],
                "title": e["title"],
                "event_type": e["event_type"],
                "location_name": e["location_name"],
                "country": e["location_country"],
                "importance": float(e["importance_score"]),
                "confidence": float(e["confidence_score"]),
                "conflict": e["conflict_flag"],
                "stories": e["story_count"],
                "sources": e["source_count"],
                "first_reported": e["first_reported_at"].isoformat() if e["first_reported_at"] else None,
                "last_reported": e["last_reported_at"].isoformat() if e["last_reported_at"] else None,
            },
        })

    return Response({"type": "FeatureCollection", "features": features})


@api_view(["GET"])
def map_entities(request):
    """Return geo-located entities as GeoJSON FeatureCollection."""
    qs = Entity.objects.filter(
        latitude__isnull=False,
        longitude__isnull=False,
    ).annotate(article_count=Count("article_entities"))

    entity_type = request.query_params.get("entity_type")
    country = request.query_params.get("country")
    min_articles = request.query_params.get("min_articles")

    if entity_type:
        qs = qs.filter(entity_type=entity_type)
    if country:
        qs = qs.filter(country=country)
    if min_articles:
        qs = qs.filter(article_count__gte=int(min_articles))

    entities = qs.values(
        "id", "name", "canonical_name", "entity_type", "country",
        "latitude", "longitude", "article_count",
    ).order_by("-article_count")[:500]

    features = []
    for e in entities:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(e["longitude"]), float(e["latitude"])],
            },
            "properties": {
                "id": e["id"],
                "name": e["name"],
                "canonical_name": e["canonical_name"],
                "entity_type": e["entity_type"],
                "country": e["country"],
                "articles": e["article_count"],
            },
        })

    return Response({"type": "FeatureCollection", "features": features})


@api_view(["GET"])
def map_alerts(request):
    """Return geo-located alerts as GeoJSON FeatureCollection.

    Alerts are geo-located via their linked event's coordinates.
    """
    from alerts.models import Alert

    severity = request.query_params.get("severity")
    alert_status = request.query_params.get("status")

    qs = Alert.objects.select_related("source", "topic").filter(
        metadata__has_key="event_id",
    )
    if severity:
        qs = qs.filter(severity=severity)
    if alert_status:
        qs = qs.filter(status=alert_status)
    else:
        qs = qs.filter(status__in=[Alert.Status.OPEN, Alert.Status.ACKNOWLEDGED])

    qs = qs.order_by("-triggered_at")[:200]

    # Batch-fetch event coordinates
    event_ids = [a.metadata.get("event_id") for a in qs if a.metadata and a.metadata.get("event_id")]
    events_geo = {}
    if event_ids:
        for e in Event.objects.filter(
            id__in=event_ids,
            location_lat__isnull=False,
            location_lon__isnull=False,
        ).values("id", "location_lat", "location_lon", "location_name", "location_country"):
            events_geo[e["id"]] = e

    features = []
    for alert in qs:
        event_id = alert.metadata.get("event_id") if alert.metadata else None
        geo = events_geo.get(event_id)
        if not geo:
            continue

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(geo["location_lon"]), float(geo["location_lat"])],
            },
            "properties": {
                "id": alert.id,
                "title": alert.title,
                "alert_type": alert.alert_type,
                "severity": alert.severity,
                "status": alert.status,
                "location_name": geo["location_name"],
                "country": geo["location_country"],
                "triggered_at": alert.triggered_at.isoformat() if alert.triggered_at else None,
            },
        })

    return Response({"type": "FeatureCollection", "features": features})


@api_view(["GET"])
def map_heat(request):
    """Heatmap weight data — event density per coordinate bucket.

    Returns weighted points for rendering heatmap overlays.
    """
    from_date = request.query_params.get("from_date")
    to_date = request.query_params.get("to_date")

    qs = Event.objects.filter(
        location_lat__isnull=False,
        location_lon__isnull=False,
    )
    if from_date:
        qs = qs.filter(first_reported_at__gte=from_date)
    if to_date:
        qs = qs.filter(last_reported_at__lte=to_date)

    # Bucket by rounded coordinates (0.5 degree grid)
    events = qs.values("location_lat", "location_lon", "importance_score")
    buckets: dict[tuple, dict] = {}
    for e in events:
        lat = round(float(e["location_lat"]) * 2) / 2
        lon = round(float(e["location_lon"]) * 2) / 2
        key = (lat, lon)
        if key not in buckets:
            buckets[key] = {"lat": lat, "lon": lon, "weight": 0, "count": 0}
        buckets[key]["count"] += 1
        buckets[key]["weight"] += float(e["importance_score"])

    points = sorted(buckets.values(), key=lambda p: -p["weight"])[:500]
    return Response({"point_count": len(points), "points": points})


@api_view(["GET"])
def map_clusters(request):
    """Cluster events by country for overview maps.

    Returns per-country aggregation with centroid approximation.
    """
    from_date = request.query_params.get("from_date")
    to_date = request.query_params.get("to_date")

    qs = Event.objects.filter(
        location_lat__isnull=False,
        location_lon__isnull=False,
    ).exclude(location_country="")

    if from_date:
        qs = qs.filter(first_reported_at__gte=from_date)
    if to_date:
        qs = qs.filter(last_reported_at__lte=to_date)

    clusters = list(
        qs.values("location_country")
        .annotate(
            event_count=Count("id"),
            avg_lat=Avg("location_lat"),
            avg_lon=Avg("location_lon"),
            avg_importance=Avg("importance_score"),
            conflict_count=Count("id", filter=Q(conflict_flag=True)),
        )
        .order_by("-event_count")[:100]
    )

    # Convert Decimal fields
    for c in clusters:
        c["avg_lat"] = float(c["avg_lat"]) if c["avg_lat"] else None
        c["avg_lon"] = float(c["avg_lon"]) if c["avg_lon"] else None
        c["avg_importance"] = float(c["avg_importance"]) if c["avg_importance"] else None

    return Response({"cluster_count": len(clusters), "clusters": clusters})
