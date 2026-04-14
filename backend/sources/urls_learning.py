"""URL routing for the Self-Learning Intelligence Layer API."""
from rest_framework.routers import DefaultRouter

from .views_learning import (
    AdaptiveThresholdViewSet,
    FeedbackViewSet,
    LearningDashboardViewSet,
    LearningRecordViewSet,
    OutcomeViewSet,
    SourceReputationViewSet,
)

router = DefaultRouter()
router.register("feedback", FeedbackViewSet, basename="feedback")
router.register("outcomes", OutcomeViewSet, basename="outcome")
router.register("reputation", SourceReputationViewSet, basename="reputation")
router.register("thresholds", AdaptiveThresholdViewSet, basename="threshold")
router.register("records", LearningRecordViewSet, basename="learning-record")
router.register("dashboard", LearningDashboardViewSet, basename="learning-dashboard")

urlpatterns = router.urls
