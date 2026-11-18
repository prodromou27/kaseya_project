from django.apps import AppConfig


class CustomFieldsConfig(AppConfig):
    name = "apps.customfields"
    label = "customfields"
    default_auto_field = "django.db.models.BigAutoField"
