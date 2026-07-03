from django.apps import AppConfig


class IdentityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.identity"

    def ready(self):
        # Register deployment-safety system checks (D-5: pepper must be set).
        from apps.identity import checks  # noqa: F401
