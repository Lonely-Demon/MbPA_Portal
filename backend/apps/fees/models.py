from django.conf import settings
from django.db import models

from apps.applications.models import Application


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

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="concessions")
    concession_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    detected_value = models.DecimalField(max_digits=12, decimal_places=4)
    benchmark_value = models.DecimalField(max_digits=12, decimal_places=4)
    premium_amount = models.DecimalField(max_digits=14, decimal_places=2)
    source = models.CharField(max_length=100, blank=True)  # e.g. "UPDR-2026 Table 4"
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fees_concession"


class FeeAssessment(models.Model):
    """Snapshot of computed fees at assessment time.

    Formula:
      scrutiny  = 50 * proposed_bua
      security  = 10 * proposed_bua
      debris    = 20 * proposed_bua
      premiums  = concession totals (FSI×1.10, OpenSpace×0.25, Parking×0.40 on Δarea × Zonal_RRR)
      total     = scrutiny + security + debris + premiums
    """
    application = models.OneToOneField(Application, on_delete=models.CASCADE, related_name="fee_assessment")
    config_version = models.ForeignKey(
        ConfigParameter, on_delete=models.PROTECT, related_name="assessments",
        null=True, blank=True,
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
    # Snapshot of bua and rrr used — assessment must not change if app data changes later
    bua_sqm_snapshot = models.DecimalField(max_digits=12, decimal_places=2)
    zonal_rrr_snapshot = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        db_table = "fees_assessment"


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
    challan_reference = models.CharField(max_length=100, db_index=True)  # not unique: re-submissions allowed
    claimed_amount = models.DecimalField(max_digits=14, decimal_places=2)
    verified_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_CLAIMED)
    payment_date = models.DateField()
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="recorded_payments"
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="verified_payments",
    )
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "fees_payment"
        indexes = [models.Index(fields=["application", "status"])]
