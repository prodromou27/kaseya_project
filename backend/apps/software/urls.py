from django.urls import include, path
from rest_framework.routers import SimpleRouter

from . import lifecycle_views, views

router = SimpleRouter()
router.register("catalog/products", views.ProductViewSet, basename="catalog-product")
router.register("catalog/aliases", views.AliasViewSet, basename="catalog-alias")
router.register("catalog/revisions", views.RevisionViewSet, basename="catalog-revision")
router.register("catalog/imports", views.ImportViewSet, basename="catalog-import")
router.register("catalog/lifecycle", lifecycle_views.LifecycleEntryViewSet, basename="catalog-lifecycle")

nested = SimpleRouter()
nested.register("software", views.CustomerSoftwareViewSet, basename="customer-software")
nested.register("software-exceptions", views.CustomerExceptionViewSet, basename="customer-software-exception")
nested.register("lifecycle", lifecycle_views.CustomerLifecycleViewSet, basename="customer-lifecycle")

urlpatterns = [
    path("", include(router.urls)),
    path("customers/<str:customer_pk>/", include(nested.urls)),
]
