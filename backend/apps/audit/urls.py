from django.urls import include, path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("audit-events", views.AuditEventViewSet, basename="audit-event")

nested = SimpleRouter()
nested.register("audit-events", views.CustomerAuditEventViewSet, basename="customer-audit-event")

urlpatterns = [
    path("", include(router.urls)),
    path("customers/<str:customer_pk>/", include(nested.urls)),
]
