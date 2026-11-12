from django.urls import include, path
from rest_framework.routers import SimpleRouter

from . import views

nested = SimpleRouter()
nested.register("os-updates", views.CustomerOsUpdateViewSet, basename="customer-os-update")

urlpatterns = [path("customers/<str:customer_pk>/", include(nested.urls))]
