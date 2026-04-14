"""Geo-Radar Service for the Early Warning system.

Identifies geographic hot zones by clustering recent events and anomalies.
Produces GeoRadarZone records with center, radius, concentration, and
temporal trend.
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Avg, Count, Q
from django.utils import timezone

from sources.models import AnomalyDetection, Event, GeoRadarZone

logger = logging.getLogger(__name__)

# Minimum events in a region to form a hot zone
MIN_ZONE_EVENTS = 3
# Grid cell size in degrees (roughly 50km at mid-latitudes)
GRID_CELL_SIZE = 0.5


def update_geo_radar() -> int:
    """Scan events and anomalies, update hot zones. Returns count of zones."""
    now = timezone.now()
    cutoff = now - timedelta(hours=48)

    # Expire old zones
    GeoRadarZone.objects.filter(
        status=GeoRadarZone.ZoneStatus.ACTIVE,
        last_activity_at__lt=now - timedelta(hours=72),
    ).update(status=GeoRadarZone.ZoneStatus.EXPIRED)

    # Gather geolocated events from last 48h
    events = list(
        Event.objects.filter(
            created_at__gte=cutoff,
            location_lat__isnull=False,
            location_lon__isnull=False,
        ).values(
            "id", "location_lat", "location_lon", "location_country",
            "location_name", "importance_score", "created_at",
        )
    )

    if not events:
        return 0

    # Grid-based clustering
    grid: dict[tuple, list] = defaultdict(list)
    for e in events:
        lat = float(e["location_lat"])
        lon = float(e["location_lon"])
        cell = (
            round(lat / GRID_CELL_SIZE) * GRID_CELL_SIZE,
            round(lon / GRID_CELL_SIZE) * GRID_CELL_SIZE,
        )
        grid[cell].append(e)

    zones_updated = 0
    for cell, cell_events in grid.items():
        if len(cell_events) < MIN_ZONE_EVENTS:
            continue

        # Compute center (centroid)
        lats = [float(e["location_lat"]) for e in cell_events]
        lons = [float(e["location_lon"]) for e in cell_events]
        center_lat = sum(lats) / len(lats)
        center_lon = sum(lons) / len(lons)

        # Radius: max distance from center
        max_dist_km = max(
            _haversine(center_lat, center_lon, float(e["location_lat"]), float(e["location_lon"]))
            for e in cell_events
        )
        radius_km = max(max_dist_km, 10.0)

        # Concentration
        area = math.pi * radius_km ** 2
        concentration = (len(cell_events) / max(area, 1.0)) * 10000  # per 100km²

        # Average importance
        avg_importance = sum(float(e["importance_score"]) for e in cell_events) / len(cell_events)

        # Country (most common)
        country_counts = defaultdict(int)
        for e in cell_events:
            cc = e["location_country"] or ""
            if cc:
                country_counts[cc] += 1
        country = max(country_counts, key=country_counts.get) if country_counts else ""

        # Location name (first non-empty)
        loc_name = ""
        for e in cell_events:
            if e.get("location_name"):
                loc_name = e["location_name"]
                break

        # Anomaly count in the zone
        anomaly_count = AnomalyDetection.objects.filter(
            detected_at__gte=cutoff,
            status=AnomalyDetection.Status.ACTIVE,
            location_country=country,
        ).count() if country else 0

        event_ids = [e["id"] for e in cell_events]

        # Temporal trend
        temporal_trend = _compute_temporal_trend(cell_events) 

        # Upsert zone
        zone, created = GeoRadarZone.objects.update_or_create(
            center_lat=Decimal(str(round(center_lat, 6))),
            center_lon=Decimal(str(round(center_lon, 6))),
            status=GeoRadarZone.ZoneStatus.ACTIVE,
            defaults={
                "title": f"Hot Zone: {loc_name or country or f'{center_lat:.2f},{center_lon:.2f}'}",
                "description": (
                    f"{len(cell_events)} events within {radius_km:.0f}km radius. "
                    f"Concentration: {concentration:.1f}/100km². Trend: {temporal_trend}."
                ),
                "radius_km": radius_km,
                "location_country": country,
                "location_name": loc_name,
                "event_count": len(cell_events),
                "event_concentration": concentration,
                "avg_severity": Decimal(str(round(avg_importance, 2))),
                "anomaly_count": anomaly_count,
                "temporal_trend": temporal_trend,
                "event_ids": event_ids,
                "last_activity_at": max(e["created_at"] for e in cell_events),
            },
        )
        zones_updated += 1

    logger.info("Geo-radar update complete: %d active zones.", zones_updated)
    return zones_updated


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def _compute_temporal_trend(events: list[dict]) -> str:
    """Determine if event activity is intensifying, stable, or subsiding."""
    if len(events) < 2:
        return "stable"

    now = timezone.now()
    recent_cutoff = now - timedelta(hours=12)

    recent = sum(1 for e in events if e["created_at"] >= recent_cutoff)
    older = len(events) - recent

    if recent > older * 1.5:
        return "intensifying"
    elif recent < older * 0.5:
        return "subsiding"
    return "stable"
