from .base import *  # noqa: F403

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

INTERNAL_IPS = ["127.0.0.1"]

# Use SQLite locally unless DATABASE_URL is set
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",  # noqa: F405
    }
}

# Disable HTTPS requirements locally
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False

# Relax CSP for local development
CSP_DEFAULT_SRC = ("'self'", "localhost:*")
CSP_SCRIPT_SRC = ("'self'", "'unsafe-eval'", "localhost:*")
