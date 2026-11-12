from django.urls import include, path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("reports", views.ReportRunViewSet, basename="report")

nested = SimpleRouter()
nested.register("reports", views.CustomerReportViewSet, basename="customer-report")
nested.register("saved-views", views.CustomerSavedViewViewSet, basename="customer-saved-view")
nested.register("report-definitions", views.CustomerReportDefinitionViewSet, basename="customer-report-definition")
nested.register("report-schedules", views.CustomerReportScheduleViewSet, basename="customer-report-schedule")
nested.register("trends", views.CustomerTrendViewSet, basename="customer-trend")

urlpatterns = [
    path("report-templates/", views.ReportTemplatesView.as_view(), name="report-templates"),
    path("", include(router.urls)),
    path("customers/<str:customer_pk>/", include(nested.urls)),
]
