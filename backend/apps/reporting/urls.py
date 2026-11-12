from django.urls import include, path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("reports", views.ReportRunViewSet, basename="report")

nested = SimpleRouter()
nested.register("reports", views.CustomerReportViewSet, basename="customer-report")

urlpatterns = [
    path("", include(router.urls)),
    path("customers/<str:customer_pk>/", include(nested.urls)),
]
