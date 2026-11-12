from django.apps import AppConfig


class PatchingConfig(AppConfig):
    name = "apps.patching"
    label = "patching"
    default_auto_field = "django.db.models.BigAutoField"
