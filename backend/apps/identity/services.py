from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import login
from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import (
    AadhaarAlreadyRegisteredError,
    DomainError,
    OtpAttemptsExceededError,
    OtpExpiredError,
)
from apps.identity.models import ApplicantProfile, OtpToken, User

# ── Aadhaar helpers ───────────────────────────────────────────────────────────


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


# ── OTP helpers ───────────────────────────────────────────────────────────────


def _hash_code(code: str) -> str:
    """SHA-256 of a 6-digit OTP code — never store the raw code."""
    return hashlib.sha256(code.encode()).hexdigest()


def request_otp(*, email: str, purpose: str, user: User | None = None) -> OtpToken:
    """
    Issue a new OTP token for the given email + purpose, invalidating any
    unconsumed prior token for the same combination.

    CRIT-5: The cumulative attempt_count from any superseded token is carried
    forward into prior_attempt_count on the new token, so resending an OTP
    does not reset the brute-force cap.
    """
    from apps.notifications.services import send_email

    prior_attempts = (
        OtpToken.objects.filter(email=email, purpose=purpose, consumed_at__isnull=True)
        .values_list("attempt_count", "prior_attempt_count")
        .first()
    )
    cumulative = sum(prior_attempts) if prior_attempts else 0
    OtpToken.objects.filter(email=email, purpose=purpose, consumed_at__isnull=True).delete()

    code = f"{secrets.randbelow(1_000_000):06d}"
    expires_at = timezone.now() + timedelta(seconds=settings.OTP_TTL_SECONDS)

    token = OtpToken.objects.create(
        user=user,
        email=email,
        purpose=purpose,
        code_hash=_hash_code(code),
        expires_at=expires_at,
        prior_attempt_count=cumulative,
    )

    template_map = {
        OtpToken.PURPOSE_LOGIN: "otp_login",
        OtpToken.PURPOSE_SIGNUP: "otp_signup",
    }
    send_email(
        email,
        template_map.get(purpose, "otp_login"),
        {"code": code, "subject": "Your MbPA Portal verification code"},
    )
    return token


def verify_otp(*, token_ref: str, submitted_code: str) -> OtpToken:
    """
    Verify a submitted OTP code against the stored hash.

    CRIT-6: token_ref is an opaque URL-safe string (not the integer PK), so
    clients cannot enumerate tokens by incrementing an ID.
    CRIT-5: The cap is checked against attempt_count + prior_attempt_count so
    resending an OTP does not reset the brute-force window.

    The attempt count is always persisted, even when the code is wrong, so
    brute-force is correctly capped (AC-06). Raising happens OUTSIDE the
    atomic block so the increment commit is not rolled back on failure.
    """
    now = timezone.now()
    exceeded = False
    wrong_code = False

    with transaction.atomic():
        try:
            token = OtpToken.objects.select_for_update().get(token_ref=token_ref)
        except OtpToken.DoesNotExist:
            raise DomainError("Invalid OTP token.") from None

        if token.consumed_at is not None:
            raise OtpExpiredError("OTP has already been used.")

        if token.expires_at < now:
            raise OtpExpiredError("OTP has expired.")

        total_attempts = token.attempt_count + token.prior_attempt_count
        if total_attempts >= settings.OTP_MAX_ATTEMPTS:
            raise OtpAttemptsExceededError("Too many incorrect attempts.")

        is_correct = hmac.compare_digest(_hash_code(submitted_code), token.code_hash)
        token.attempt_count += 1
        token.save(update_fields=["attempt_count"])

        if is_correct:
            token.consumed_at = now
            token.save(update_fields=["consumed_at"])
        else:
            total = token.attempt_count + token.prior_attempt_count
            exceeded = total >= settings.OTP_MAX_ATTEMPTS
            wrong_code = True

    # Raise outside the atomic block so the attempt-count commit is not rolled back
    if wrong_code:
        if exceeded:
            raise OtpAttemptsExceededError("Too many incorrect attempts.")
        raise DomainError("Invalid OTP code.")

    return token


# ── Registration ──────────────────────────────────────────────────────────────


@transaction.atomic
def register_applicant(
    *,
    email: str,
    username: str,
    password: str,
    full_name: str,
    aadhaar_raw: str,
) -> tuple[User, OtpToken]:
    """
    Create a new applicant User + ApplicantProfile, then issue a signup OTP.

    Raises AadhaarAlreadyRegisteredError if the Aadhaar is already on file;
    sends a fraud-alert email to the existing account holder before raising.
    """
    from apps.identity.selectors import get_registered_owner_email
    from apps.notifications.services import EmailDeliveryError, send_email

    aadhaar_hash = hash_aadhaar(aadhaar_raw)

    owner_email = get_registered_owner_email(aadhaar_hash)
    if owner_email is not None:
        # M-7: the alert must reach the account being impersonated, not the
        # new signup's supplied email — sending it to the new registrant just
        # tells a would-be attacker "your own email was attempted," which is
        # meaningless as a fraud alert. `email` (the new signup's address) is
        # still passed into the template so the real owner can see what
        # address the attempt used.
        #
        # M-6: the alert is a best-effort side notification — its delivery
        # failing must not swallow or replace the AadhaarAlreadyRegisteredError
        # below (already logged inside send_email on failure).
        try:
            send_email(
                owner_email,
                "aadhaar_reuse_alert",
                {"email": email, "subject": "MbPA Portal — Duplicate registration attempt"},
            )
        except EmailDeliveryError:
            pass
        raise AadhaarAlreadyRegisteredError("An account with this Aadhaar number already exists.")

    last4 = _normalize_aadhaar(aadhaar_raw)[-4:]

    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
        user_type=User.USER_TYPE_APPLICANT,
    )

    ApplicantProfile.objects.create(
        user=user,
        full_name=full_name,
        aadhaar_hash=aadhaar_hash,
        aadhaar_last4=last4,
    )

    token = request_otp(email=email, purpose=OtpToken.PURPOSE_SIGNUP, user=user)
    return user, token


# ── Session management ────────────────────────────────────────────────────────


def login_issue_session(request, user: User) -> None:
    """Log the user in and set a role-appropriate session TTL."""
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    if user.user_type in (User.USER_TYPE_OFFICER, User.USER_TYPE_ADMIN):
        request.session.set_expiry(settings.OFFICER_SESSION_TTL_SECONDS)
    else:
        request.session.set_expiry(settings.APPLICANT_SESSION_TTL_SECONDS)
