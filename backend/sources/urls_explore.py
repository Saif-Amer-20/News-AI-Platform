"""URL routing for the analyst exploration API."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from sources.views_explore import (
    EntityExplorerViewSet,
    EventExplorerViewSet,
    global_timeline,
    graph_neighbors,
    graph_shortest_path,
    map_entities,
    map_events,
    search_articles,
    search_events,
)

router = DefaultRouter()
router.register("events", EventExplorerViewSet, basename="explore-events")
router.register("entities", EntityExplorerViewSet, basename="explore-entities")

urlpatterns = [
    path("", include(router.urls)),

    # Graph traversal
    path("graph/neighbors/", graph_neighbors, name="graph-neighbors"),
    path("graph/path/", graph_shortest_path, name="graph-shortest-path"),

    # Map
    path("map/events/", map_events, name="map-events"),
    path("map/entities/", map_entities, name="map-entities"),

    # Timeline
    path("timeline/", global_timeline, name="global-timeline"),

    # Full-text search
    path("search/articles/", search_articles, name="search-articles"),
    path("search/events/", search_events, name="search-events"),
]
