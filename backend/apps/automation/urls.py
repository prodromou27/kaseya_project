from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .script_views import (
    CustomerScriptCollectorsView,
    CustomerScriptValueViewSet,
    ScriptCatalogView,
    ScriptCollectorViewSet,
)
from .views import AutomationCatalogView, CustomerAutomationViewSet

router = SimpleRouter()
router.register("script-collectors", ScriptCollectorViewSet, basename="script-collector")

nested = SimpleRouter()
nested.register("automation", CustomerAutomationViewSet, basename="customer-automation")
nested.register("script-values", CustomerScriptValueViewSet, basename="customer-script-value")

urlpatterns = [
    path("automation/catalog/", AutomationCatalogView.as_view(), name="automation-catalog"),
    path("automation/scripts/", ScriptCatalogView.as_view(), name="automation-scripts"),
    path("", include(router.urls)),
    path(
        "customers/<str:customer_pk>/script-collectors/",
        CustomerScriptCollectorsView.as_view(),
        name="customer-script-collectors",
    ),
    path("customers/<str:customer_pk>/", include(nested.urls)),
]
