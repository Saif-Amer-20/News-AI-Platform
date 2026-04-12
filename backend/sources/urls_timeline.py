"""URL routing for the Timeline Explorer API."""
from django.urls import path

from .views_timeline import (
    alert_timeline,
    case_timeline,
    entity_timeline,
    global_timeline,
    topic_timeline,
)

urlpatterns = [
    path("", global_timeline, name="global-timeline"),
    path("entities/<int:entity_id>/", entity_timeline, name="entity-timeline"),
    path("topics/<int:topic_id>/", topic_timeline, name="topic-timeline"),
    path("alerts/", alert_timeline, name="alert-timeline"),
    path("cases/<int:case_id>/", case_timeline, name="case-timeline"),
]
