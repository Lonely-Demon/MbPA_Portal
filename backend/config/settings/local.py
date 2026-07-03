from .base import *  # noqa: F403

DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

INTERNAL_IPS = ["127.0.0.1"]

# Use SQLite locally unless DATABASE_URL is set.
# Bug fix: this used to unconditionally hardcode sqlite, silently ignoring
# DATABASE_URL — CI sets DATABASE_URL to a real Postgres service container
# specifically so Postgres-only behavior (the audit-log trigger, gapless
# numbering under real row locks) gets exercised, but every test gated on
# connection.vendor == "postgresql" was skipping there too, unnoticed.
if env("DATABASE_URL", default=""):  # noqa: F405
    DATABASES = {"default": env.db("DATABASE_URL")}  # noqa: F405
else:
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

# Bug fix: the Vite dev server (npm run dev, port 5173) proxies /api/* to this
# server on port 8000 with changeOrigin=true — but changeOrigin only rewrites
# the Host header sent upstream, not Origin/Referer, which the browser still
# sends as http://localhost:5173. Django 4+'s CSRF origin check compares that
# against this server's own scheme+host and rejects the mismatch with a 403
# on every mutating request, regardless of a valid CSRF cookie/token — so the
# documented local dev flow (`npm run dev` + Django on :8000) never actually
# worked against a real browser without this.
CSRF_TRUSTED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

# Relax CSP for local development
CSP_DEFAULT_SRC = ("'self'", "localhost:*")
CSP_SCRIPT_SRC = ("'self'", "'unsafe-eval'", "localhost:*")

# Expose the OpenAPI schema + Swagger UI locally for `npm run generate:api`.
SERVE_API_SCHEMA = True

# Single dev server, no proxy in front — let ipware read REMOTE_ADDR directly.
AXES_IPWARE_PROXY_COUNT = 0
