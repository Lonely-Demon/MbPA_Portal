"""
Deployment-safety system checks for the identity app.

D-5: AADHAAR_PEPPER must be configured before any Aadhaar is hashed. The
hash_aadhaar() service already fails loudly at first use, but that is too late —
a production deploy with the pepper missing boots cleanly and only errors when
the first applicant registers. This check moves the failure to startup
(manage.py check, run in CI and on boot) whenever DEBUG is off, so a misconfigured
production environment is caught before it serves traffic.
"""

from __future__ import annotations

from django.conf import settings
from django.core.checks import Error, register


@register()
def aadhaar_pepper_configured(app_configs, **kwargs):
    errors = []
    if not settings.DEBUG and not getattr(settings, "AADHAAR_PEPPER", ""):
        errors.append(
            Error(
                "AADHAAR_PEPPER is not set.",
                hint=(
                    "Set the AADHAAR_PEPPER environment variable to a high-entropy "
                    "secret. An empty pepper makes the Aadhaar HMAC a fixed, "
                    "keyless function — trivially reversible offline."
                ),
                id="identity.E001",
            )
        )
    return errors
