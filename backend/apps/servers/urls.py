from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .views import OwnerGroupViewSet, ServerViewSet

nested = SimpleRouter()
nested.register("server-owner-groups", OwnerGroupViewSet, basename="server-owner-group")
nested.register("servers", ServerViewSet, basename="customer-server")

urlpatterns = [path("customers/<str:customer_pk>/", include(nested.urls))]
