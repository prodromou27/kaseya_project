from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView

urlpatterns = [
    path("health/", include("apps.core.urls")),
    path("auth/", include("apps.accounts.urls")),
    path("", include("apps.accounts.admin_urls")),
    path("", include("apps.customers.urls")),
    path("", include("apps.integrations.urls")),
    path("", include("apps.audit.urls")),
    path("", include("apps.reporting.urls")),
    path("schema/", SpectacularAPIView.as_view(), name="api-schema"),
]
