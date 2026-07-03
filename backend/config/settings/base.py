from pathlib import Path

import environ

env = environ.Env()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

SECRET_KEY = env("DJANGO_SECRET_KEY")

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "drf_spectacular",
    "simple_history",
    "axes",
    "csp",
    "storages",
]

LOCAL_APPS = [
    "apps.identity",
    "apps.applications",
    "apps.documents",
    "apps.fees",
    "apps.certificates",
    "apps.compliance",
    "apps.api",
    "apps.notifications",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.identity.middleware.IdleTimeoutMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    "axes.middleware.AxesMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "csp.middleware.CSPMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

AUTH_USER_MODEL = "identity.User"

DATABASES = {
    "default": env.db("DATABASE_URL", default="sqlite:///db.sqlite3"),
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "mediafiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── OTP / Session TTL ─────────────────────────────────────────────────────────
OTP_TTL_SECONDS = 600  # 10 minutes
OTP_MAX_ATTEMPTS = 5
APPLICANT_SESSION_TTL_SECONDS = 45 * 60  # 45 minutes
OFFICER_SESSION_TTL_SECONDS = 6 * 60 * 60  # 6 hours

# ── DRF ──────────────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # HIGH-5: ScopedRateThrottle alone only limits the handful of views that
    # declare a throttle_scope (signup/login/otp/otp_resend) — every other
    # endpoint (uploads, downloads, fee assessment, etc.) had zero rate
    # limiting. Anon/User throttles below give every endpoint a floor.
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.ScopedRateThrottle",
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "signup": "5/min",
        "login": "5/min",
        "otp": "5/min",
        "otp_resend": "3/min",
        "anon": "60/min",
        "user": "300/min",
    },
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.common.exceptions.domain_exception_handler",
}

# ── drf-spectacular ───────────────────────────────────────────────────────────
SPECTACULAR_SETTINGS = {
    "TITLE": "MbPA Building Permission Portal API",
    "DESCRIPTION": (
        "Mumbai Port Authority Special Planning Authority — UPDR-2026 building permission workflow."
    ),
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

# Whether to mount the live /api/schema/ + swagger routes. Off by default so they
# are never exposed in production; local.py turns it on for frontend codegen.
SERVE_API_SCHEMA = env.bool("SERVE_API_SCHEMA", default=False)

# ── django-axes (brute-force protection) ─────────────────────────────────────
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # hour
AXES_LOCKOUT_PARAMETERS = ["username", "ip_address"]
# Number of trusted reverse proxies in front of Django (nginx = 1; add the count
# of any LB/CDN ahead of it). Without this, django-ipware honours the leftmost,
# client-supplied X-Forwarded-For entry — letting an attacker spoof the IP to
# bypass the lockout, or pin a victim's IP to lock them out. Counting from the
# right, the (n+1)-th-from-right address is the real client. Override per-env.
AXES_IPWARE_PROXY_COUNT = env.int("AXES_IPWARE_PROXY_COUNT", default=1)
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# ── Session ───────────────────────────────────────────────────────────────────
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = False  # React must read csrftoken
CSRF_COOKIE_SAMESITE = "Lax"

# ── Backblaze B2 (django-storages S3-compatible API) ─────────────────────────
B2_KEY_ID = env("B2_KEY_ID", default="")
B2_APPLICATION_KEY = env("B2_APPLICATION_KEY", default="")
B2_BUCKET_NAME = env("B2_BUCKET_NAME", default="mbpa-portal")
B2_REGION = env("B2_REGION", default="")  # e.g. us-west-004

if B2_KEY_ID:
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "bucket_name": B2_BUCKET_NAME,
                "endpoint_url": f"https://s3.{B2_REGION}.backblazeb2.com",
                "region_name": B2_REGION,
                "signature_version": "s3v4",
                "access_key": B2_KEY_ID,
                "secret_key": B2_APPLICATION_KEY,
                "default_acl": None,
                "querystring_auth": True,
                "querystring_expire": 300,  # AC-21: 5-minute presign TTL
                "file_overwrite": False,  # belt-and-suspenders alongside AC-20 versioning
            },
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }

DOCUMENT_MAX_UPLOAD_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB global cap; per-slot overrides deferred

# ── DSC signing ───────────────────────────────────────────────────────────────
# Path to the CCA trust-root DER file used to validate officer DSC signatures.
# In dev/test, point at a placeholder; swap for real CCA root in production.
DSC_TRUST_ROOT_PATH = env("DSC_TRUST_ROOT_PATH", default=str(BASE_DIR / "cca_trust_root.der"))

# HIGH-3: "soft-fail" (pyhanko_certvalidator's default) treats an unreachable
# CRL/OCSP responder as "not revoked" — a network outage or a blocked responder
# silently downgrades revocation checking to a no-op. "hard-fail" requires a
# fresh, affirmative revocation status for every cert in the chain (except
# trust anchors), so an unreachable revocation service fails closed instead
# of open.
DSC_REVOCATION_MODE = env("DSC_REVOCATION_MODE", default="hard-fail")
# Required for hard-fail to have anything to check: without fetching enabled,
# there is never any revocation info available and every validation would fail.
DSC_ALLOW_REVOCATION_FETCHING = env.bool("DSC_ALLOW_REVOCATION_FETCHING", default=True)

# ── Email (Resend via SMTP) ───────────────────────────────────────────────────
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = "smtp.resend.com"
EMAIL_PORT = 587
EMAIL_HOST_USER = "resend"
EMAIL_HOST_PASSWORD = env("RESEND_API_KEY", default="")
EMAIL_USE_TLS = True
DEFAULT_FROM_EMAIL = env(
    "DEFAULT_FROM_EMAIL",
    default="Mumbai Port Authority <noreply@mbpa.example.gov>",
)

# ── Aadhaar HMAC pepper ───────────────────────────────────────────────────────
# Must be high-entropy secret, never stored in DB. Rotate by re-hashing.
AADHAAR_PEPPER = env("AADHAAR_PEPPER", default="")

# ── django-csp (Content-Security-Policy; migrate to native SECURE_CSP on Django 6.x) ──
CSP_DEFAULT_SRC: tuple[str, ...] = ("'self'",)
CSP_SCRIPT_SRC: tuple[str, ...] = ("'self'",)
CSP_STYLE_SRC = ("'self'",)
CSP_FONT_SRC = ("'self'", "https://fonts.gstatic.com")
CSP_IMG_SRC = ("'self'", "data:")
CSP_CONNECT_SRC = ("'self'",)
CSP_FRAME_ANCESTORS = ("'none'",)

# ── Logging (AC-31: sensitive-data redaction backstop) ────────────────────────
# The SensitiveDataFilter is attached to every handler so raw Aadhaar numbers,
# OTP codes, passwords, and secrets are masked before they reach any sink — in
# dev, test, and production alike. production.py overrides handlers/formatters
# but reuses this same filter.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "redact_sensitive": {
            "()": "apps.common.logging.SensitiveDataFilter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["redact_sensitive"],
        },
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "apps": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
