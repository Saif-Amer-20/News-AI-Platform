"""Public API URL routing for the Alerts domain."""
from rest_framework.routers import DefaultRouter

from .views_api import AlertViewSet

router = DefaultRouter()
router.register("alerts", AlertViewSet, basename="alert")

urlpatterns = router.urls
