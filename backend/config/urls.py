from django.contrib import admin
from django.urls import include, path

from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from core.admin_site import NewsIntelAdminSite

# Replace the default admin site with our custom grouped version.
# We subclass but use the default site's registry by making it the
# default site *before* apps register their models.
# Since models already registered on admin.site, we create a thin wrapper.


class _ProxiedOpsAdmin(NewsIntelAdminSite):
    """Delegates model registry to the default admin.site while overriding
    get_app_list for logical grouping."""

    @property
    def _registry(self):
        return admin.site._registry

    @_registry.setter
    def _registry(self, value):
        pass  # ignore; we always read from admin.site

    def has_permission(self, request):
        return admin.site.has_permission(request)


newsintel_admin = _ProxiedOpsAdmin()

urlpatterns = [
    # ── Auth (JWT) ────────────────────────────────────────────
    path("api/v1/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/v1/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),

    # ── System ────────────────────────────────────────────────
    path("api/v1/system/", include("core.urls")),

    # ── Analyst Product Layer ─────────────────────────────────
    path("api/v1/dashboard/", include("core.urls_dashboard")),
    path("api/v1/", include("sources.urls_api")),
    path("api/v1/", include("alerts.urls_api")),
    path("api/v1/", include("cases.urls_api")),
    path("api/v1/map/", include("sources.urls_map")),
    path("api/v1/timeline/", include("sources.urls_timeline")),
    path("api/v1/graph/", include("sources.urls_graph")),
    path("api/v1/search/", include("sources.urls_search")),

    # ── Early Warning & Predictive Intelligence ───────────────
    path("api/v1/early-warning/", include("sources.urls_early_warning")),

    # ── Self-Learning Intelligence Layer ──────────────────────
    path("api/v1/learning/", include("sources.urls_learning")),

    # ── Entity Intelligence Layer ──────────────────────────────
    path("api/v1/entity-intelligence/", include("sources.urls_entity_intelligence")),

    # ── Legacy explore namespace (kept for backward compat) ───
    path("api/v1/explore/", include("sources.urls_explore")),

    # ── Internal / Admin ──────────────────────────────────────
    path("api/internal/", include("sources.urls_internal")),
    path("ops/admin/", newsintel_admin.urls),
    path("", include("django_prometheus.urls")),
]
