from django.urls import include, path
from rest_framework.routers import SimpleRouter

from . import views

nested = SimpleRouter()
nested.register("onboarding/uploads", views.UploadViewSet, basename="onboarding-upload")
nested.register("onboarding/templates", views.TemplateViewSet, basename="onboarding-template")
nested.register("onboarding/runs", views.RunViewSet, basename="onboarding-run")

urlpatterns = [path("customers/<str:customer_pk>/", include(nested.urls))]
