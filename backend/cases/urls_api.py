"""URL routing for the Cases API."""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views_api import CaseViewSet, SavedSearchViewSet

router = DefaultRouter()
router.register("cases", CaseViewSet)
router.register("saved-searches", SavedSearchViewSet)
router.register("saved-views", SavedSearchViewSet, basename="saved-view")

urlpatterns = [
    path("", include(router.urls)),
]
