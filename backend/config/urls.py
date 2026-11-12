from django.urls import include, path

from apps.core.errors import json_404, json_500

urlpatterns = [
    path("api/v1/", include("config.api_urls")),
]

handler404 = json_404
handler500 = json_500
