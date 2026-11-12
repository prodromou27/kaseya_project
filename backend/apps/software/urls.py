from django.urls import include, path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("catalog/products", views.ProductViewSet, basename="catalog-product")
router.register("catalog/aliases", views.AliasViewSet, basename="catalog-alias")
router.register("catalog/revisions", views.RevisionViewSet, basename="catalog-revision")
router.register("catalog/imports", views.ImportViewSet, basename="catalog-import")

nested = SimpleRouter()
nested.register("software", views.CustomerSoftwareViewSet, basename="customer-software")
nested.register("software-exceptions", views.CustomerExceptionViewSet, basename="customer-software-exception")

urlpatterns = [
    path("", include(router.urls)),
    path("customers/<str:customer_pk>/", include(nested.urls)),
]
