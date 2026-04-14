"""URL routing for the Early Warning & Predictive Intelligence API."""
from rest_framework.routers import DefaultRouter

from .views_early_warning import (
    AnomalyDetectionViewSet,
    EarlyWarningDashboardViewSet,
    GeoRadarZoneViewSet,
    HistoricalPatternViewSet,
    PredictiveScoreViewSet,
    SignalCorrelationViewSet,
)

router = DefaultRouter()
router.register("anomalies", AnomalyDetectionViewSet, basename="anomaly")
router.register("correlations", SignalCorrelationViewSet, basename="correlation")
router.register("predictions", PredictiveScoreViewSet, basename="prediction")
router.register("patterns", HistoricalPatternViewSet, basename="pattern")
router.register("geo-radar", GeoRadarZoneViewSet, basename="geo-radar")
router.register("dashboard", EarlyWarningDashboardViewSet, basename="early-warning-dashboard")

urlpatterns = router.urls
