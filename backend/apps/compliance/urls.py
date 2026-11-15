from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .views import ComplianceBaselineViewSet

nested = SimpleRouter()
nested.register("compliance-baselines", ComplianceBaselineViewSet, basename="compliance-baseline")

urlpatterns = [path("customers/<str:customer_pk>/", include(nested.urls))]
