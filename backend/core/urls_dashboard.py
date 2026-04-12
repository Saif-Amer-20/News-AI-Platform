"""URL routing for the Dashboard / Command Center API."""
from django.urls import path

from .views_dashboard import (
    conflict_events,
    dashboard_overview,
    high_priority_events,
    recent_alerts,
    source_health,
    watchlist_hits,
)

urlpatterns = [
    path("overview/", dashboard_overview, name="dashboard-overview"),
    path("high-priority-events/", high_priority_events, name="dashboard-high-priority-events"),
    path("watchlist-hits/", watchlist_hits, name="dashboard-watchlist-hits"),
    path("conflict-events/", conflict_events, name="dashboard-conflict-events"),
    path("recent-alerts/", recent_alerts, name="dashboard-recent-alerts"),
    path("source-health/", source_health, name="dashboard-source-health"),
]
