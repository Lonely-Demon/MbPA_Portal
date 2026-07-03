from django.conf import settings
from django.db import models

from apps.applications.models import Application


class Certificate(models.Model):
    """
    Issued certificates. Rows are NEVER deleted (statutory permanence).
    Revocation is recorded via revoked_at; the row and R2 object are retained.
    """

    TYPE_AIP = "aip"
    TYPE_DEVELOPMENT_PERM = "development_permission"
    TYPE_COMMENCEMENT_PLINTH = "commencement_plinth"
    TYPE_FURTHER_COMMENCEMENT = "further_commencement"
    TYPE_COMMENCEMENT_80PCT = "commencement_80pct"
    TYPE_COMMENCEMENT_REM20 = "commencement_rem20"
    TYPE_BUILDING_COMPLETION = "building_completion"
    TYPE_OC = "oc"
    TYPE_DEMOLITION_CLEARANCE = "demolition_clearance"
    TYPE_CHOICES = [
        (TYPE_AIP, "Approval in Principle"),
        (TYPE_DEVELOPMENT_PERM, "Development Permission"),
        (TYPE_COMMENCEMENT_PLINTH, "Commencement Certificate to Plinth"),
        (TYPE_FURTHER_COMMENCEMENT, "Further Commencement Certificate"),
        (TYPE_COMMENCEMENT_80PCT, "Commencement Certificate (80% BUA)"),
        (TYPE_COMMENCEMENT_REM20, "Commencement Certificate (Remaining 20%)"),
        (TYPE_BUILDING_COMPLETION, "Building Completion Certificate"),
        (TYPE_OC, "Occupancy Certificate"),
        (TYPE_DEMOLITION_CLEARANCE, "Demolition & Site Clearance Certificate"),
    ]

    application = models.ForeignKey(
        Application, on_delete=models.PROTECT, related_name="certificates"
    )
    certificate_type = models.CharField(max_length=25, choices=TYPE_CHOICES)
    certificate_number = models.CharField(max_length=30, unique=True)

    # R2 object key for the signed PDF; presigned URLs generated on demand
    r2_object_key = models.CharField(max_length=512)
    # pyHanko DSC verification result
    signature_verified = models.BooleanField(default=False)
    dsc_serial_used = models.CharField(max_length=128, blank=True)

    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="issued_certificates"
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    valid_until = models.DateField(null=True, blank=True)

    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="revoked_certificates",
    )
    revocation_reason = models.TextField(blank=True)

    class Meta:
        db_table = "certificates_certificate"
        indexes = [
            models.Index(fields=["application", "certificate_type"]),
            models.Index(fields=["certificate_number"]),
        ]

    def __str__(self):
        return self.certificate_number
