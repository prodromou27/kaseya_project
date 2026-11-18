from django.urls import include, path
from rest_framework.routers import SimpleRouter

from .views import CustomFieldViewSet, DefinitionSettingsViewSet, JobViewSet

router = SimpleRouter()
router.register("custom-field-definitions", DefinitionSettingsViewSet, basename="custom-field-definition")

nested = SimpleRouter()
nested.register("custom-fields", CustomFieldViewSet, basename="customer-custom-field")
nested.register("custom-field-jobs", JobViewSet, basename="customer-custom-field-job")

urlpatterns = [path("", include(router.urls)), path("customers/<str:customer_pk>/", include(nested.urls))]
