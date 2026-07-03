"""
Deployment-safety system checks for the certificates app.

H-1: cca_trust_root.der ships as a 12-byte placeholder file so the repo
boots without a real CCA (Controller of Certifying Authorities) root
certificate checked in. receive_signed_certificate() only discovers a bad
trust root the first time an officer uploads a signed certificate, at
which point DSC signature verification either fails unpredictably or, in
the worst case, silently validates against nothing meaningful. This check
mirrors identity.E001 (AADHAAR_PEPPER) by moving that failure to startup
(manage.py check, run in CI and on boot) whenever DEBUG is off.
"""

from __future__ import annotations

from django.conf import settings
from django.core.checks import Error, register


@register()
def dsc_trust_root_is_valid_certificate(app_configs, **kwargs):
    errors = []
    if settings.DEBUG:
        return errors

    trust_root_path = getattr(settings, "DSC_TRUST_ROOT_PATH", "")
    hint = (
        "Set DSC_TRUST_ROOT_PATH to a real CCA root certificate (DER-encoded "
        "X.509) before go-live. The checked-in cca_trust_root.der is a "
        "placeholder and must be replaced, not just left in place."
    )

    try:
        with open(trust_root_path, "rb") as fh:
            der_bytes = fh.read()
    except OSError as exc:
        errors.append(
            Error(
                f"DSC trust root file could not be read at {trust_root_path!r}: {exc}",
                hint=hint,
                id="certificates.E001",
            )
        )
        return errors

    from asn1crypto import x509 as asn1_x509

    try:
        asn1_x509.Certificate.load(der_bytes)
    except ValueError:
        errors.append(
            Error(
                f"DSC_TRUST_ROOT_PATH ({trust_root_path}) is not a valid DER X.509 certificate.",
                hint=hint,
                id="certificates.E001",
            )
        )
    return errors
