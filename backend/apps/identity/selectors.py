from __future__ import annotations

from django.contrib.auth import get_user_model

from apps.identity.models import ApplicantProfile

User = get_user_model()


def check_aadhaar_dedup(aadhaar_hash: str) -> bool:
    """Return True if the Aadhaar hash is already registered to any profile."""
    return ApplicantProfile.objects.filter(aadhaar_hash=aadhaar_hash).exists()


def get_user_for_login(*, email: str, username: str) -> User | None:
    """Return the User whose email AND username both match, or None."""
    try:
        return User.objects.get(email=email, username=username)
    except User.DoesNotExist:
        return None
