from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView

from apps.core.views import SystemStatusView

urlpatterns = [
    path("health/", include("apps.core.urls")),
    path("system/status/", SystemStatusView.as_view(), name="system-status"),
    path("auth/", include("apps.accounts.urls")),
    path("", include("apps.accounts.admin_urls")),
    path("", include("apps.customers.urls")),
    path("", include("apps.integrations.urls")),
    path("", include("apps.audit.urls")),
    path("", include("apps.reporting.urls")),
    path("", include("apps.inventory.urls")),
    path("", include("apps.software.urls")),
    path("", include("apps.patching.urls")),
    path("", include("apps.onboarding.urls")),
    path("", include("apps.compliance.urls")),
    path("", include("apps.alerts.urls")),
    path("", include("apps.automation.urls")),
    path("", include("apps.servers.urls")),
    path("", include("apps.customfields.urls")),
    path("schema/", SpectacularAPIView.as_view(), name="api-schema"),
]
