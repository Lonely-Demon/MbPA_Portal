import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.common.exceptions import (
    AadhaarAlreadyRegisteredError,
    OtpAttemptsExceededError,
    OtpExpiredError,
)
from apps.identity.models import ApplicantProfile, OfficerProfile, OtpToken
from apps.identity.selectors import check_aadhaar_dedup, get_user_for_login
from apps.identity.serializers import (
    LoginRequestSerializer,
    MeSerializer,
    OtpVerifySerializer,
    SignupSerializer,
)
from apps.identity.services import (
    _normalize_aadhaar,
    aadhaar_matches,
    hash_aadhaar,
    login_issue_session,
    register_applicant,
    verify_otp,
)

User = get_user_model()

VALID_AADHAAR = "123456789012"
VALID_AADHAAR_SPACED = "1234 5678 9012"
VALID_AADHAAR_HYPHEN = "1234-5678-9012"
PEPPER_A = "pepper-aaaa-test-value-64-chars-long-placeholder-xxxxxxxxxxxxxxxxx"
PEPPER_B = "pepper-bbbb-test-value-64-chars-long-placeholder-xxxxxxxxxxxxxxxxx"


# ── _normalize_aadhaar ────────────────────────────────────────────────────────


def test_normalize_strips_spaces():
    assert _normalize_aadhaar(VALID_AADHAAR_SPACED) == VALID_AADHAAR


def test_normalize_strips_hyphens():
    assert _normalize_aadhaar(VALID_AADHAAR_HYPHEN) == VALID_AADHAAR


def test_normalize_accepts_plain_digits():
    assert _normalize_aadhaar(VALID_AADHAAR) == VALID_AADHAAR


def test_normalize_rejects_too_short():
    with pytest.raises(ValueError, match="12 digits"):
        _normalize_aadhaar("12345")


def test_normalize_rejects_too_long():
    with pytest.raises(ValueError, match="12 digits"):
        _normalize_aadhaar("1234567890123")  # 13 digits


def test_normalize_rejects_letters():
    with pytest.raises(ValueError, match="12 digits"):
        _normalize_aadhaar("ABCDEFGHIJKL")


def test_normalize_rejects_empty():
    with pytest.raises(ValueError, match="12 digits"):
        _normalize_aadhaar("")


# ── hash_aadhaar ──────────────────────────────────────────────────────────────


@override_settings(AADHAAR_PEPPER=PEPPER_A)
def test_hash_aadhaar_returns_64_char_hex():
    result = hash_aadhaar(VALID_AADHAAR)
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


@override_settings(AADHAAR_PEPPER=PEPPER_A)
def test_hash_aadhaar_is_deterministic():
    """Same input + same pepper must always produce the same hash."""
    assert hash_aadhaar(VALID_AADHAAR) == hash_aadhaar(VALID_AADHAAR)


@override_settings(AADHAAR_PEPPER=PEPPER_A)
def test_hash_aadhaar_normalises_spacing():
    """Spaced and unspaced forms of the same number must produce identical hashes."""
    assert hash_aadhaar(VALID_AADHAAR_SPACED) == hash_aadhaar(VALID_AADHAAR)
    assert hash_aadhaar(VALID_AADHAAR_HYPHEN) == hash_aadhaar(VALID_AADHAAR)


@override_settings(AADHAAR_PEPPER=PEPPER_A)
def test_hash_aadhaar_different_number_gives_different_hash():
    other = "999999999999"
    assert hash_aadhaar(VALID_AADHAAR) != hash_aadhaar(other)


def test_hash_aadhaar_pepper_changes_output():
    """Different peppers must produce different hashes — pepper is not ignored."""
    with override_settings(AADHAAR_PEPPER=PEPPER_A):
        hash_a = hash_aadhaar(VALID_AADHAAR)
    with override_settings(AADHAAR_PEPPER=PEPPER_B):
        hash_b = hash_aadhaar(VALID_AADHAAR)
    assert hash_a != hash_b


@override_settings(AADHAAR_PEPPER="")
def test_hash_aadhaar_raises_without_pepper():
    """Hashing without a pepper must raise ValueError loudly."""
    with pytest.raises(ValueError, match="AADHAAR_PEPPER"):
        hash_aadhaar(VALID_AADHAAR)


@override_settings(AADHAAR_PEPPER=None)
def test_hash_aadhaar_raises_when_pepper_is_none():
    with pytest.raises(ValueError, match="AADHAAR_PEPPER"):
        hash_aadhaar(VALID_AADHAAR)


# ── aadhaar_matches ───────────────────────────────────────────────────────────


@override_settings(AADHAAR_PEPPER=PEPPER_A)
def test_aadhaar_matches_true_for_same_input():
    stored = hash_aadhaar(VALID_AADHAAR)
    assert aadhaar_matches(VALID_AADHAAR, stored) is True


@override_settings(AADHAAR_PEPPER=PEPPER_A)
def test_aadhaar_matches_true_normalised_vs_plain():
    """Verifying a spaced entry against a hash of the plain digits must succeed."""
    stored = hash_aadhaar(VALID_AADHAAR)
    assert aadhaar_matches(VALID_AADHAAR_SPACED, stored) is True


@override_settings(AADHAAR_PEPPER=PEPPER_A)
def test_aadhaar_matches_false_for_different_number():
    stored = hash_aadhaar(VALID_AADHAAR)
    assert aadhaar_matches("999999999999", stored) is False


@override_settings(AADHAAR_PEPPER=PEPPER_A)
def test_aadhaar_matches_false_for_tampered_hash():
    stored = hash_aadhaar(VALID_AADHAAR)
    tampered = stored[:-1] + ("0" if stored[-1] != "0" else "1")
    assert aadhaar_matches(VALID_AADHAAR, tampered) is False


# ── OTP services — brute-force cap (AC-06) ────────────────────────────────────


@pytest.mark.django_db
@override_settings(
    AADHAAR_PEPPER=PEPPER_A,
    OTP_TTL_SECONDS=600,
    OTP_MAX_ATTEMPTS=5,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
def test_otp_correct_code_succeeds():
    token = OtpToken.objects.create(
        email="a@test.com",
        purpose=OtpToken.PURPOSE_LOGIN,
        code_hash=__import__("hashlib").sha256(b"123456").hexdigest(),
        expires_at=timezone.now() + __import__("datetime").timedelta(minutes=10),
    )
    result = verify_otp(token_ref=token.token_ref, submitted_code="123456")
    assert result.consumed_at is not None


@pytest.mark.django_db
@override_settings(OTP_TTL_SECONDS=600, OTP_MAX_ATTEMPTS=5)
def test_otp_wrong_code_increments_attempt_count():
    import datetime
    import hashlib

    token = OtpToken.objects.create(
        email="b@test.com",
        purpose=OtpToken.PURPOSE_LOGIN,
        code_hash=hashlib.sha256(b"999999").hexdigest(),
        expires_at=timezone.now() + datetime.timedelta(minutes=10),
    )
    with pytest.raises(Exception):
        verify_otp(token_ref=token.token_ref, submitted_code="000000")
    token.refresh_from_db()
    assert token.attempt_count == 1


@pytest.mark.django_db
@override_settings(OTP_TTL_SECONDS=600, OTP_MAX_ATTEMPTS=3)
def test_otp_attempt_cap_raises_exceeded_error():
    import datetime
    import hashlib

    token = OtpToken.objects.create(
        email="c@test.com",
        purpose=OtpToken.PURPOSE_LOGIN,
        code_hash=hashlib.sha256(b"999999").hexdigest(),
        expires_at=timezone.now() + datetime.timedelta(minutes=10),
    )
    for _ in range(2):
        with pytest.raises(Exception):
            verify_otp(token_ref=token.token_ref, submitted_code="000000")

    with pytest.raises(OtpAttemptsExceededError):
        verify_otp(token_ref=token.token_ref, submitted_code="000000")


@pytest.mark.django_db
@override_settings(OTP_TTL_SECONDS=600, OTP_MAX_ATTEMPTS=5)
def test_otp_expired_token_raises():
    import datetime
    import hashlib

    token = OtpToken.objects.create(
        email="d@test.com",
        purpose=OtpToken.PURPOSE_LOGIN,
        code_hash=hashlib.sha256(b"123456").hexdigest(),
        expires_at=timezone.now() - datetime.timedelta(minutes=1),
    )
    with pytest.raises(OtpExpiredError):
        verify_otp(token_ref=token.token_ref, submitted_code="123456")


@pytest.mark.django_db
@override_settings(OTP_TTL_SECONDS=600, OTP_MAX_ATTEMPTS=5)
def test_otp_consumed_token_raises():
    import datetime
    import hashlib

    token = OtpToken.objects.create(
        email="e@test.com",
        purpose=OtpToken.PURPOSE_LOGIN,
        code_hash=hashlib.sha256(b"123456").hexdigest(),
        expires_at=timezone.now() + datetime.timedelta(minutes=10),
        consumed_at=timezone.now(),
    )
    with pytest.raises(OtpExpiredError):
        verify_otp(token_ref=token.token_ref, submitted_code="123456")


@pytest.mark.django_db
@override_settings(OTP_MAX_ATTEMPTS=5, OTP_TTL_SECONDS=600)
def test_otp_attempt_count_persists_after_wrong_code():
    """Attempt increments must survive even when an exception is raised (AC-06)."""
    import datetime
    import hashlib

    token = OtpToken.objects.create(
        email="f@test.com",
        purpose=OtpToken.PURPOSE_LOGIN,
        code_hash=hashlib.sha256(b"999999").hexdigest(),
        expires_at=timezone.now() + datetime.timedelta(minutes=10),
    )
    with pytest.raises(Exception):
        verify_otp(token_ref=token.token_ref, submitted_code="111111")

    token.refresh_from_db()
    assert token.attempt_count == 1  # Increment persisted despite exception


# ── Aadhaar deduplication ─────────────────────────────────────────────────────


@pytest.mark.django_db
@override_settings(AADHAAR_PEPPER=PEPPER_A)
def test_check_aadhaar_dedup_false_when_no_profile():
    h = hash_aadhaar(VALID_AADHAAR)
    assert check_aadhaar_dedup(h) is False


@pytest.mark.django_db
@override_settings(AADHAAR_PEPPER=PEPPER_A)
def test_check_aadhaar_dedup_true_after_registration():
    user = User.objects.create_user(username="deduptest", email="dd@test.com", password="pw")
    h = hash_aadhaar(VALID_AADHAAR)
    ApplicantProfile.objects.create(
        user=user, full_name="Test", aadhaar_hash=h, aadhaar_last4="9012"
    )
    assert check_aadhaar_dedup(h) is True


@pytest.mark.django_db
@override_settings(
    AADHAAR_PEPPER=PEPPER_A,
    OTP_TTL_SECONDS=600,
    OTP_MAX_ATTEMPTS=5,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
def test_register_applicant_duplicate_aadhaar_raises():
    # Register first user
    User.objects.create_user(username="first", email="first@test.com", password="pw")
    h = hash_aadhaar(VALID_AADHAAR)
    ApplicantProfile.objects.create(
        user=User.objects.get(username="first"),
        full_name="First",
        aadhaar_hash=h,
        aadhaar_last4="9012",
    )

    with pytest.raises(AadhaarAlreadyRegisteredError):
        register_applicant(
            email="second@test.com",
            username="second",
            password="securepass123",
            full_name="Second",
            aadhaar_raw=VALID_AADHAAR,
        )


@pytest.mark.django_db
@override_settings(
    AADHAAR_PEPPER=PEPPER_A,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
def test_register_applicant_duplicate_aadhaar_alerts_original_owner_not_new_registrant():
    """
    M-7: the fraud alert must reach the account being impersonated, not the
    new signup's supplied email. Sending it to the new registrant only tells
    a would-be attacker "your own email was attempted" — useless as an
    alert, and the point of a fraud alert is to warn the actual victim.
    """
    from django.core import mail

    owner = User.objects.create_user(
        username="original_owner", email="original_owner@test.com", password="pw"
    )
    h = hash_aadhaar(VALID_AADHAAR)
    ApplicantProfile.objects.create(
        user=owner,
        full_name="Original Owner",
        aadhaar_hash=h,
        aadhaar_last4="9012",
    )

    with pytest.raises(AadhaarAlreadyRegisteredError):
        register_applicant(
            email="attacker@test.com",
            username="attacker",
            password="securepass123",
            full_name="Attacker",
            aadhaar_raw=VALID_AADHAAR,
        )

    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert sent.to == ["original_owner@test.com"]
    assert "attacker@test.com" not in sent.to
    # The alert still tells the real owner what email the attempt used.
    assert "attacker@test.com" in sent.body


@pytest.mark.django_db
@override_settings(AADHAAR_PEPPER=PEPPER_A)
def test_register_applicant_duplicate_aadhaar_raises_even_if_alert_email_fails():
    """
    M-6: send_email now raises on failure instead of swallowing silently.
    The fraud-alert email is a best-effort side notification — its failure
    must not swallow or replace AadhaarAlreadyRegisteredError.
    """
    from unittest.mock import patch

    User.objects.create_user(username="first2", email="first2@test.com", password="pw")
    h = hash_aadhaar(VALID_AADHAAR)
    ApplicantProfile.objects.create(
        user=User.objects.get(username="first2"),
        full_name="First",
        aadhaar_hash=h,
        aadhaar_last4="9012",
    )

    with patch("apps.notifications.services.send_mail", side_effect=OSError("smtp down")):
        with pytest.raises(AadhaarAlreadyRegisteredError):
            register_applicant(
                email="second2@test.com",
                username="second2",
                password="securepass123",
                full_name="Second",
                aadhaar_raw=VALID_AADHAAR,
            )


@pytest.mark.django_db
@override_settings(
    AADHAAR_PEPPER=PEPPER_A,
    OTP_TTL_SECONDS=600,
    OTP_MAX_ATTEMPTS=5,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
def test_register_applicant_success_creates_profile():
    user, token = register_applicant(
        email="new@test.com",
        username="newuser",
        password="securepass123",
        full_name="New User",
        aadhaar_raw=VALID_AADHAAR,
    )
    assert user.pk is not None
    assert user.user_type == User.USER_TYPE_APPLICANT
    assert ApplicantProfile.objects.filter(user=user).exists()
    profile = ApplicantProfile.objects.get(user=user)
    assert profile.aadhaar_last4 == "9012"
    assert token.purpose == OtpToken.PURPOSE_SIGNUP


# ── Session TTL (AC-10) ───────────────────────────────────────────────────────


@pytest.mark.django_db
@override_settings(
    APPLICANT_SESSION_TTL_SECONDS=2700,
    OFFICER_SESSION_TTL_SECONDS=21600,
    AXES_ENABLED=False,
)
def test_login_issue_session_applicant_ttl():
    from unittest.mock import MagicMock, patch

    user = User.objects.create_user(
        username="applicant_ttl",
        email="ap@test.com",
        password="pw",
        user_type=User.USER_TYPE_APPLICANT,
    )
    request = MagicMock()
    request.session = MagicMock()
    with patch("apps.identity.services.login"):
        login_issue_session(request, user)
    request.session.set_expiry.assert_called_once_with(2700)


@pytest.mark.django_db
@override_settings(
    APPLICANT_SESSION_TTL_SECONDS=2700,
    OFFICER_SESSION_TTL_SECONDS=21600,
    AXES_ENABLED=False,
)
def test_login_issue_session_officer_ttl():
    from unittest.mock import MagicMock, patch

    user = User.objects.create_user(
        username="officer_ttl",
        email="of@test.com",
        password="pw",
        user_type=User.USER_TYPE_OFFICER,
    )
    OfficerProfile.objects.create(user=user, role=OfficerProfile.ROLE_JUNIOR_PLANNER)
    request = MagicMock()
    request.session = MagicMock()
    with patch("apps.identity.services.login"):
        login_issue_session(request, user)
    request.session.set_expiry.assert_called_once_with(21600)


# ── Selector: get_user_for_login ──────────────────────────────────────────────


@pytest.mark.django_db
def test_get_user_for_login_returns_user_when_both_match():
    User.objects.create_user(username="ulogin", email="ulogin@test.com", password="pw")
    result = get_user_for_login(email="ulogin@test.com", username="ulogin")
    assert result is not None
    assert result.username == "ulogin"


@pytest.mark.django_db
def test_get_user_for_login_returns_none_when_email_wrong():
    User.objects.create_user(username="ulogin2", email="right@test.com", password="pw")
    result = get_user_for_login(email="wrong@test.com", username="ulogin2")
    assert result is None


@pytest.mark.django_db
def test_get_user_for_login_returns_none_when_username_wrong():
    User.objects.create_user(username="ulogin3", email="right3@test.com", password="pw")
    result = get_user_for_login(email="right3@test.com", username="wrongname")
    assert result is None


# ── Mass-assignment protection (AC-12) ───────────────────────────────────────


def test_signup_serializer_no_extra_fields():
    """SignupSerializer must not expose unexpected fields."""
    allowed = {"email", "username", "password", "full_name", "aadhaar"}
    ser = SignupSerializer()
    assert set(ser.fields.keys()) == allowed


def test_login_serializer_no_extra_fields():
    allowed = {"email", "username", "password"}
    ser = LoginRequestSerializer()
    assert set(ser.fields.keys()) == allowed


def test_otp_verify_serializer_no_extra_fields():
    allowed = {"token_ref", "code"}
    ser = OtpVerifySerializer()
    assert set(ser.fields.keys()) == allowed


@pytest.mark.django_db
def test_me_serializer_read_only_fields():
    """All MeSerializer fields must be read-only (AC-12)."""
    user = User.objects.create_user(username="metest", email="me@test.com", password="pw")
    ser = MeSerializer(user)
    for field_name, field in ser.fields.items():
        assert field.read_only, f"Field '{field_name}' should be read-only"


# ── Login view: three-credential check ───────────────────────────────────────


@pytest.mark.django_db
@override_settings(
    OTP_TTL_SECONDS=600,
    OTP_MAX_ATTEMPTS=5,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
def test_login_view_correct_credentials_issues_otp():
    User.objects.create_user(
        username="loginok",
        email="loginok@test.com",
        password="goodpassword123",
    )
    client = APIClient()
    resp = client.post(
        "/api/identity/login/",
        {"email": "loginok@test.com", "username": "loginok", "password": "goodpassword123"},
        format="json",
    )
    assert resp.status_code == 200
    assert "token_ref" in resp.data
    assert "masked_email" in resp.data


@pytest.mark.django_db
@override_settings(OTP_TTL_SECONDS=600, OTP_MAX_ATTEMPTS=5)
def test_login_view_returns_error_when_otp_email_delivery_fails():
    """
    M-6: request_otp() no longer swallows email delivery failures. A caller
    must not be told login succeeded (200 + token_ref) when the OTP that
    token_ref refers to was never actually delivered.
    """
    from unittest.mock import patch

    User.objects.create_user(
        username="loginfail",
        email="loginfail@test.com",
        password="goodpassword123",
    )
    client = APIClient()
    with patch("apps.notifications.services.send_mail", side_effect=OSError("smtp down")):
        resp = client.post(
            "/api/identity/login/",
            {"email": "loginfail@test.com", "username": "loginfail", "password": "goodpassword123"},
            format="json",
        )
    assert resp.status_code == 409


@pytest.mark.django_db
def test_login_view_wrong_password_returns_401():
    User.objects.create_user(
        username="loginbad",
        email="loginbad@test.com",
        password="correctpassword",
    )
    client = APIClient()
    resp = client.post(
        "/api/identity/login/",
        {"email": "loginbad@test.com", "username": "loginbad", "password": "wrongpassword"},
        format="json",
    )
    assert resp.status_code == 401
    assert resp.data["detail"] == "Invalid credentials."


@pytest.mark.django_db
def test_login_view_wrong_email_returns_401():
    """Third credential: correct username+password but email doesn't match."""
    User.objects.create_user(
        username="login3cred",
        email="real@test.com",
        password="goodpass123",
    )
    client = APIClient()
    resp = client.post(
        "/api/identity/login/",
        {"email": "fake@test.com", "username": "login3cred", "password": "goodpass123"},
        format="json",
    )
    assert resp.status_code == 401
    assert resp.data["detail"] == "Invalid credentials."


# ── django-axes lockout (AC-06) ───────────────────────────────────────────────


@pytest.mark.django_db
@override_settings(AXES_FAILURE_LIMIT=5, AXES_COOLOFF_TIME=1)
def test_axes_lockout_after_five_failed_logins():
    """After 5 failed login attempts, django-axes should block the account."""
    User.objects.create_user(
        username="axestest",
        email="axestest@test.com",
        password="correctpassword",
    )
    client = APIClient()
    for _ in range(5):
        client.post(
            "/api/identity/login/",
            {
                "email": "axestest@test.com",
                "username": "axestest",
                "password": "wrongpassword",
            },
            format="json",
        )

    # 6th attempt — should be blocked (axes 403 or DRF throttle 429)
    resp = client.post(
        "/api/identity/login/",
        {
            "email": "axestest@test.com",
            "username": "axestest",
            "password": "wrongpassword",
        },
        format="json",
    )
    # 403 = axes lockout, 429 = DRF ScopedRateThrottle — both mean the account is protected
    assert resp.status_code in (403, 429)


# ── AADHAAR_PEPPER startup enforcement (D-5) ──────────────────────────────────


def test_aadhaar_pepper_check_errors_when_unset_in_production():
    """D-5: manage.py check must fail when AADHAAR_PEPPER is empty and DEBUG=False."""
    from django.test import override_settings

    from apps.identity.checks import aadhaar_pepper_configured

    with override_settings(DEBUG=False, AADHAAR_PEPPER=""):
        errors = aadhaar_pepper_configured(None)
    assert [e.id for e in errors] == ["identity.E001"]


def test_aadhaar_pepper_check_passes_when_set():
    from django.test import override_settings

    from apps.identity.checks import aadhaar_pepper_configured

    with override_settings(DEBUG=False, AADHAAR_PEPPER="x" * 32):
        assert aadhaar_pepper_configured(None) == []


def test_aadhaar_pepper_check_silent_in_debug():
    """An empty pepper in local dev (DEBUG=True) must not block startup."""
    from django.test import override_settings

    from apps.identity.checks import aadhaar_pepper_configured

    with override_settings(DEBUG=True, AADHAAR_PEPPER=""):
        assert aadhaar_pepper_configured(None) == []
