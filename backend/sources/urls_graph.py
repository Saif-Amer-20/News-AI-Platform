"""URL routing for the Graph Explorer API (Neo4j traversal)."""
from django.urls import path

from .views_explore import graph_neighbors, graph_shortest_path

urlpatterns = [
    path("neighbors/", graph_neighbors, name="graph-neighbors"),
    path("path/", graph_shortest_path, name="graph-shortest-path"),
]
