import environ

from .base import *  # noqa: F403

env = environ.Env()

DEBUG = False

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS")

# ── HTTPS / HSTS ──────────────────────────────────────────────────────────────
# Ramp HSTS from a small value first; increase to 31536000 after confirming.
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 300  # raise to 31536000 after go-live
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"

CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

# ── Email via Resend SMTP ─────────────────────────────────────────────────────
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

# ── Logging ───────────────────────────────────────────────────────────────────
# AC-31: the redact_sensitive filter is attached to every handler so no raw
# Aadhaar / OTP / password / secret can reach the log sink, even via tracebacks.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "redact_sensitive": {
            "()": "apps.common.logging.SensitiveDataFilter",
        },
    },
    "formatters": {
        "json": {
            "()": "django.utils.log.ServerFormatter",
            "format": '{"time": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s"}',
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["redact_sensitive"],
        },
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "apps": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
