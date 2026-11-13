from django.urls import include, path
from rest_framework.routers import SimpleRouter

from . import changes_views, details_views, health_views, network_views, views

router = SimpleRouter()
router.register("assets", views.AssetDetailViewSet, basename="asset")

nested = SimpleRouter()
nested.register("assets", views.CustomerAssetViewSet, basename="customer-asset")
nested.register("datasets", views.DatasetStatusViewSet, basename="customer-dataset")
nested.register("sync-runs", views.CustomerSyncRunViewSet, basename="customer-sync-run")
nested.register("hierarchy", views.CustomerHierarchyViewSet, basename="customer-hierarchy")
nested.register("groups", views.CustomerGroupViewSet, basename="customer-group")
nested.register("device-health", health_views.CustomerDeviceHealthViewSet, basename="customer-device-health")
nested.register("health-thresholds", health_views.HealthThresholdsViewSet, basename="customer-health-thresholds")
nested.register("notifications", details_views.CustomerNotificationViewSet, basename="customer-notification")
nested.register(
    "custom-field-allowlist", details_views.CustomFieldAllowlistViewSet, basename="customer-custom-field-allowlist"
)
nested.register("changes", changes_views.CustomerChangesViewSet, basename="customer-changes")
nested.register("expected-subnets", network_views.ExpectedSubnetViewSet, basename="customer-expected-subnet")

urlpatterns = [
    path("", include(router.urls)),
    path("customers/<str:customer_pk>/", include(nested.urls)),
]
