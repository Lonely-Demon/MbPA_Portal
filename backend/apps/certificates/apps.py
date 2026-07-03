from django.apps import AppConfig


class CertificatesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.certificates"

    def ready(self):
        # Register deployment-safety system checks (H-1: trust root must be real).
        from apps.certificates import checks  # noqa: F401
