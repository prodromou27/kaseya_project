from django.urls import include, path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("customers", views.CustomerViewSet, basename="customer")
router.register("mappings", views.MappingReviewViewSet, basename="mapping-review")

nested = SimpleRouter()
nested.register("memberships", views.MembershipViewSet, basename="customer-membership")
nested.register("mappings", views.SourceMappingViewSet, basename="customer-mapping")

urlpatterns = [
    path("", include(router.urls)),
    path("customers/<str:customer_pk>/", include(nested.urls)),
]
