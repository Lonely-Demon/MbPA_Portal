import hashlib
import hmac

from django.conf import settings


def hash_aadhaar(raw: str) -> str:
    """
    Return HMAC-SHA256(aadhaar_digits, pepper) as a 64-char hex string.

    The pepper lives in settings.AADHAAR_PEPPER (env var; never in the DB).
    Raises ValueError if the pepper is not configured — failing loudly is
    intentional: storing an unpepped hash defeats the entire threat model.
    """
    pepper = getattr(settings, "AADHAAR_PEPPER", "")
    if not pepper:
        raise ValueError(
            "AADHAAR_PEPPER is not set. Cannot hash Aadhaar without a pepper. "
            "Set the AADHAAR_PEPPER environment variable."
        )
    return hmac.new(
        pepper.encode("utf-8"),
        raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def aadhaar_matches(raw: str, stored_hash: str) -> bool:
    """Constant-time comparison to prevent timing attacks."""
    return hmac.compare_digest(hash_aadhaar(raw), stored_hash)
