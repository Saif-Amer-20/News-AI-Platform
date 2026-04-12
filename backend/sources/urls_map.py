"""URL routing for the Map Explorer API."""
from django.urls import path

from .views_map import map_alerts, map_clusters, map_entities, map_events, map_heat

urlpatterns = [
    path("events/", map_events, name="map-events"),
    path("entities/", map_entities, name="map-entities"),
    path("alerts/", map_alerts, name="map-alerts"),
    path("heat/", map_heat, name="map-heat"),
    path("clusters/", map_clusters, name="map-clusters"),
]
