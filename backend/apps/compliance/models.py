from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.applications.models import Application, MilestoneInstance


class ConditionalClearance(models.Model):
    """Conditions attached to a clearance grant that must be fulfilled."""

    TYPE_NOC = "noc"
    TYPE_STRUCTURAL = "structural"
    TYPE_FIRE = "fire"
    TYPE_ENVIRONMENT = "environment"
    TYPE_HERITAGE = "heritage"
    TYPE_OTHER = "other"
    TYPE_CHOICES = [
        (TYPE_NOC, "No-Objection Certificate"),
        (TYPE_STRUCTURAL, "Structural Stability"),
        (TYPE_FIRE, "Fire Safety"),
        (TYPE_ENVIRONMENT, "Environmental Clearance"),
        (TYPE_HERITAGE, "Heritage Clearance"),
        (TYPE_OTHER, "Other"),
    ]

    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name="conditional_clearances"
    )
    milestone_instance = models.ForeignKey(
        MilestoneInstance,
        on_delete=models.PROTECT,
        related_name="conditional_clearances",
        null=True,
        blank=True,
    )
    clearance_type = models.CharField(max_length=15, choices=TYPE_CHOICES)
    description = models.TextField()
    # Structured metadata (agency name, reference number, expiry, etc.)
    trigger_metadata = models.JSONField(default=dict)
    is_fulfilled = models.BooleanField(default=False)
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    fulfilled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="fulfilled_clearances",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "compliance_conditional_clearance"


class Complaint(models.Model):
    ORIGIN_APPLICANT = "applicant_raised"
    ORIGIN_SYSTEM = "system_raised"
    ORIGIN_CHOICES = [
        (ORIGIN_APPLICANT, "Applicant Raised"),
        (ORIGIN_SYSTEM, "System Raised"),
    ]
    STATUS_OPEN = "open"
    STATUS_IN_REVIEW = "in_review"
    STATUS_RESOLVED = "resolved"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_IN_REVIEW, "In Review"),
        (STATUS_RESOLVED, "Resolved"),
        (STATUS_CLOSED, "Closed"),
    ]

    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name="complaints"
    )
    origin = models.CharField(max_length=20, choices=ORIGIN_CHOICES)
    raised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="raised_complaints",
    )
    subject = models.CharField(max_length=255)
    body = models.TextField()
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_OPEN)
    resolution_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "compliance_complaint"
        indexes = [models.Index(fields=["application", "status"])]


class AuditEvent(models.Model):
    """
    Append-only audit log. Rows must NEVER be updated or deleted.

    Enforcement is layered:
      1. Model-level: save() raises on pk-present calls; delete() always raises.
      2. DB-level: a BEFORE UPDATE OR DELETE trigger raises an exception (added in migration).
      3. DB-level: the application DB user has INSERT-only on this table
         (documented in deployment runbook).

    target_type / target_id use plain fields (not GenericForeignKey) to avoid
    content-type table coupling and to allow queries without joins.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    verb = models.CharField(max_length=100)  # e.g. "application.submitted"
    target_type = models.CharField(max_length=100)  # e.g. "Application"
    target_id = models.BigIntegerField()
    payload = models.JSONField(default=dict)  # diff / before-after snapshot
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    # Monotonic sequence maintained by DB BIGSERIAL — see migration
    sequence = models.BigIntegerField(unique=True, editable=False, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "compliance_audit_event"
        indexes = [
            models.Index(fields=["target_type", "target_id"]),
            models.Index(fields=["actor", "created_at"]),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("AuditEvent rows are immutable — updates are forbidden.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("AuditEvent rows are permanent — deletion is forbidden.")


class Holiday(models.Model):
    """Public / bank holiday calendar used by SLA working-day calculations."""

    date = models.DateField(unique=True)
    description = models.CharField(max_length=200)
    is_national = models.BooleanField(default=True)

    class Meta:
        db_table = "compliance_holiday"
        ordering = ["date"]

    def __str__(self):
        return f"{self.date} - {self.description}"
