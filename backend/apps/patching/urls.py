from django.urls import include, path
from rest_framework.routers import SimpleRouter

from . import policy_views, views

nested = SimpleRouter()
nested.register("os-updates", views.CustomerOsUpdateViewSet, basename="customer-os-update")
nested.register("patch-policies", policy_views.CustomerPatchPolicyViewSet, basename="customer-patch-policy")
nested.register("patch-policy-baselines", policy_views.ExpectedPatchPolicyViewSet, basename="customer-patch-baseline")

urlpatterns = [path("customers/<str:customer_pk>/", include(nested.urls))]
