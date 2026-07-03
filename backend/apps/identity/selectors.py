from __future__ import annotations

from apps.identity.models import ApplicantProfile, User


def check_aadhaar_dedup(aadhaar_hash: str) -> bool:
    """Return True if the Aadhaar hash is already registered to any profile."""
    return ApplicantProfile.objects.filter(aadhaar_hash=aadhaar_hash).exists()


def get_registered_owner_email(aadhaar_hash: str) -> str | None:
    """
    Return the email of the account already registered under this Aadhaar
    hash, or None if it isn't registered. M-7: used to route the duplicate-
    Aadhaar fraud alert to the legitimate account holder, not the new
    signup's supplied email — the account being impersonated is the one that
    actually needs to know about the attempt.
    """
    profile = (
        ApplicantProfile.objects.select_related("user").filter(aadhaar_hash=aadhaar_hash).first()
    )
    return profile.user.email if profile else None


def get_user_for_login(*, email: str, username: str) -> User | None:
    """Return the User whose email AND username both match, or None."""
    try:
        return User.objects.get(email=email, username=username)
    except User.DoesNotExist:
        return None
