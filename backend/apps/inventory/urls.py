from django.urls import include, path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("assets", views.AssetDetailViewSet, basename="asset")

nested = SimpleRouter()
nested.register("assets", views.CustomerAssetViewSet, basename="customer-asset")
nested.register("datasets", views.DatasetStatusViewSet, basename="customer-dataset")
nested.register("sync-runs", views.CustomerSyncRunViewSet, basename="customer-sync-run")

urlpatterns = [
    path("", include(router.urls)),
    path("customers/<str:customer_pk>/", include(nested.urls)),
]
