from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .views import AlertSubscriptionViewSet, AlertViewSet

router = SimpleRouter()
router.register("alert-subscriptions", AlertSubscriptionViewSet, basename="alert-subscription")
router.register("alerts", AlertViewSet, basename="alert")

urlpatterns = [path("", include(router.urls))]
