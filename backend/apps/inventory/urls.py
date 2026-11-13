from django.urls import include, path
from rest_framework.routers import SimpleRouter

from . import health_views, views

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

urlpatterns = [
    path("", include(router.urls)),
    path("customers/<str:customer_pk>/", include(nested.urls)),
]
