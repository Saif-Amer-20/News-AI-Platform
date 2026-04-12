"""Public API URL routing for the Sources domain.

Events and entities use unified viewsets that combine CRUD with
analyst exploration (replacing the old fragmented EventViewSet +
EventExplorerViewSet pattern).
"""
from rest_framework.routers import DefaultRouter

from .views_api import (
    ArticleViewSet,
    SourceViewSet,
    StoryViewSet,
)
from .views_entities import EntityViewSet
from .views_events import EventViewSet

router = DefaultRouter()
router.register("sources", SourceViewSet, basename="source")
router.register("articles", ArticleViewSet, basename="article")
router.register("stories", StoryViewSet, basename="story")
router.register("events", EventViewSet, basename="event")
router.register("entities", EntityViewSet, basename="entity")

urlpatterns = router.urls
