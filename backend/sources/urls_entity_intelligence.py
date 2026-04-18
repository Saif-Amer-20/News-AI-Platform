"""URL routing for the Entity Intelligence Layer.

Mounted at /api/v1/entity-intelligence/ in config/urls.py.
"""
from django.urls import path

from .views_entity_intelligence import (
    dashboard_summary,
    emerging_entities,
    entity_detail,
    entity_graph,
    influence_ranking,
    mark_signal_read,
    relationship_type_stats,
    signals_feed,
    strongest_relationships,
)

urlpatterns = [
    path("dashboard/",         dashboard_summary,        name="ei-dashboard"),
    path("graph/",             entity_graph,             name="ei-graph"),
    path("influence/",         influence_ranking,        name="ei-influence"),
    path("emerging/",          emerging_entities,        name="ei-emerging"),
    path("signals/",           signals_feed,             name="ei-signals"),
    path("signals/<int:signal_id>/read/", mark_signal_read, name="ei-signal-read"),
    path("relationship-types/", relationship_type_stats, name="ei-rel-types"),
    path("strongest/",         strongest_relationships,  name="ei-strongest"),
    path("entities/<int:entity_id>/", entity_detail,     name="ei-entity-detail"),
]
