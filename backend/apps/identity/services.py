import hashlib
import hmac
import re

from django.conf import settings


def _normalize_aadhaar(raw: str) -> str:
    """
    Strip all non-digit characters and validate exactly 12 digits remain.

    Aadhaar numbers are commonly entered with spaces ("1234 5678 9012") or
    hyphens; the same person would hash to different values without this step,
    silently defeating deduplication.
    """
    digits = re.sub(r"\D", "", raw)
    if len(digits) != 12:
        raise ValueError(
            f"Aadhaar must be exactly 12 digits after stripping non-digits; "
            f"got {len(digits)} digit(s) from input of length {len(raw)}."
        )
    return digits


def hash_aadhaar(raw: str) -> str:
    """
    Return HMAC-SHA256(normalized_aadhaar_digits, pepper) as a 64-char hex string.

    Input is normalised before hashing: spaces, hyphens, and any other non-digit
    characters are stripped, then length is validated to exactly 12 digits.

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
    normalized = _normalize_aadhaar(raw)
    return hmac.new(
        pepper.encode("utf-8"),
        normalized.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def aadhaar_matches(raw: str, stored_hash: str) -> bool:
    """Constant-time comparison to prevent timing attacks."""
    return hmac.compare_digest(hash_aadhaar(raw), stored_hash)
