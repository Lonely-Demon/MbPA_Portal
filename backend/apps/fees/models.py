from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.applications.models import Application
from apps.common.exceptions import FeeAssessmentLockedError


class ConfigParameter(models.Model):
    """Versioned key-value store for fee rates, thresholds, and other config.

    Each row is immutable after creation — create a new row to change a value,
    with a new effective_from date. The row with the latest effective_from ≤ now
    is the active value.
    """

    key = models.CharField(max_length=100)
    value = models.CharField(max_length=500)
    effective_from = models.DateField()
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="config_parameters"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fees_config_parameter"
        indexes = [models.Index(fields=["key", "effective_from"])]
        get_latest_by = "effective_from"

    def __str__(self):
        return f"{self.key} ({self.effective_from})"


class FeeAssessment(models.Model):
    """Snapshot of computed fees at assessment time.

    Multiple rows may exist per application; at most one has is_current=True
    (enforced by the partial unique constraint). Reassessment marks the old row
    is_current=False and creates a new one — history is never deleted.

    Once a payment is verified, is_locked=True is set and any further mutation
    via save() raises FeeAssessmentLockedError (AC-16).

    config_version snapshots the scrutiny_fee_per_sqm ConfigParameter in effect
    at assessment time. All seven config values used in the calculation are
    captured in the audit event payload for full traceability.
    """

    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name="fee_assessments"
    )
    config_version = models.ForeignKey(
        ConfigParameter,
        on_delete=models.PROTECT,
        related_name="assessments",
        null=True,
        blank=True,
    )

    scrutiny_fee = models.DecimalField(max_digits=14, decimal_places=2)
    security_deposit = models.DecimalField(max_digits=14, decimal_places=2)
    debris_deposit = models.DecimalField(max_digits=14, decimal_places=2)
    premium_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2)

    assessed_at = models.DateTimeField(auto_now_add=True)
    assessed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="fee_assessments"
    )
    bua_sqm_snapshot = models.DecimalField(max_digits=12, decimal_places=2)
    zonal_rrr_snapshot = models.DecimalField(max_digits=12, decimal_places=2)

    is_current = models.BooleanField(default=True)
    is_locked = models.BooleanField(default=False)
    locked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "fees_assessment"
        constraints = [
            models.UniqueConstraint(
                fields=["application"],
                condition=Q(is_current=True),
                name="one_current_fee_assessment_per_app",
            )
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            try:
                current = FeeAssessment.objects.get(pk=self.pk)
            except FeeAssessment.DoesNotExist:
                pass
            else:
                if current.is_locked:
                    raise FeeAssessmentLockedError(
                        "AC-16: FeeAssessment is locked after payment has been verified."
                    )
        super().save(*args, **kwargs)


class Concession(models.Model):
    """Premium / concession detected on an application parcel."""

    TYPE_FSI = "fsi"
    TYPE_OPEN_SPACE = "open_space"
    TYPE_PARKING = "parking"
    TYPE_CHOICES = [
        (TYPE_FSI, "FSI"),
        (TYPE_OPEN_SPACE, "Open Space"),
        (TYPE_PARKING, "Parking"),
    ]

    DETECTION_AUTO = "auto"
    DETECTION_DECLARED = "declared"
    DETECTION_CHOICES = [
        (DETECTION_AUTO, "Auto-detected"),
        (DETECTION_DECLARED, "Applicant-declared"),
    ]

    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name="concessions"
    )
    concession_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    detected_value = models.DecimalField(max_digits=12, decimal_places=4)
    benchmark_value = models.DecimalField(max_digits=12, decimal_places=4)
    premium_amount = models.DecimalField(max_digits=14, decimal_places=2)
    source = models.CharField(max_length=100, blank=True)
    detection_method = models.CharField(
        max_length=10, choices=DETECTION_CHOICES, default=DETECTION_AUTO
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fees_concession"


class Payment(models.Model):
    STATUS_CLAIMED = "claimed"
    STATUS_VERIFIED = "verified"
    STATUS_REJECTED = "rejected"
    STATUS_MISMATCH = "mismatch"
    STATUS_CHOICES = [
        (STATUS_CLAIMED, "Claimed"),
        (STATUS_VERIFIED, "Verified"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_MISMATCH, "Amount Mismatch"),
    ]

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="payments")
    assessment = models.ForeignKey(FeeAssessment, on_delete=models.PROTECT, related_name="payments")
    challan_reference = models.CharField(max_length=100, db_index=True)
    claimed_amount = models.DecimalField(max_digits=14, decimal_places=2)
    verified_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_CLAIMED)
    payment_date = models.DateField()
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="recorded_payments"
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_payments",
    )
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "fees_payment"
        indexes = [models.Index(fields=["application", "status"])]
