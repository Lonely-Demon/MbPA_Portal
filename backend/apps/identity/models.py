from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    USER_TYPE_APPLICANT = "applicant"
    USER_TYPE_OFFICER = "officer"
    USER_TYPE_ADMIN = "admin"
    USER_TYPE_CHOICES = [
        (USER_TYPE_APPLICANT, "Applicant"),
        (USER_TYPE_OFFICER, "Officer"),
        (USER_TYPE_ADMIN, "Admin"),
    ]

    user_type = models.CharField(
        max_length=10, choices=USER_TYPE_CHOICES, default=USER_TYPE_APPLICANT
    )
    mobile = models.CharField(max_length=15, blank=True)
    is_mobile_verified = models.BooleanField(default=False)

    class Meta:
        db_table = "identity_user"

    def __str__(self):
        return self.username


class ApplicantProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="applicant_profile")
    full_name = models.CharField(max_length=255)
    pan_number = models.CharField(max_length=10, blank=True)
    # Aadhaar never stored raw; only HMAC-SHA256(aadhaar, pepper) + last 4 digits
    aadhaar_hash = models.CharField(max_length=64, blank=True, db_index=True)
    aadhaar_last4 = models.CharField(max_length=4, blank=True)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "identity_applicant_profile"

    def __str__(self):
        return self.full_name


class OfficerProfile(models.Model):
    ROLE_ESTATE_OFFICER = "estate_officer"
    ROLE_JUNIOR_PLANNER = "junior_planner"
    ROLE_DEPUTY_PLANNER = "deputy_planner"
    ROLE_CHAIRMAN = "chairman"
    ROLE_CHOICES = [
        (ROLE_ESTATE_OFFICER, "Estate Officer"),
        (ROLE_JUNIOR_PLANNER, "Junior Planner"),
        (ROLE_DEPUTY_PLANNER, "Deputy Planner"),
        (ROLE_CHAIRMAN, "Chairman"),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="officer_profile")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    zone = models.CharField(max_length=100, blank=True)
    stream_specialisation = models.CharField(max_length=50, blank=True)
    # DSC certificate serial for pyHanko signing
    dsc_serial = models.CharField(max_length=128, blank=True)
    is_active_officer = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "identity_officer_profile"

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.get_role_display()})"


class OtpToken(models.Model):
    """Short-lived OTP; rows are hard-deleted after verification or expiry."""

    PURPOSE_LOGIN = "login"
    PURPOSE_MOBILE_VERIFY = "mobile_verify"
    PURPOSE_CHOICES = [
        (PURPOSE_LOGIN, "Login"),
        (PURPOSE_MOBILE_VERIFY, "Mobile Verify"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="otp_tokens")
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES)
    code_hash = models.CharField(max_length=64)  # SHA-256 of 6-digit code
    attempt_count = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "identity_otp_token"
        indexes = [models.Index(fields=["user", "purpose", "expires_at"])]
