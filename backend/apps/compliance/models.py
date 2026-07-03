from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.applications.models import Application, MilestoneInstance


class ConditionalClearance(models.Model):
    """Conditions attached to a clearance grant that must be fulfilled."""

    # PRD §2.3, §6.6 — five named clearance authorities from the 7-question NOC wizard.
    TYPE_RAILWAY = "railway"  # Railway Authority NOC
    TYPE_CRZ = "crz"  # CRZ / MCZMA Coastal Regulation Zone
    TYPE_HERITAGE_MHCC = "heritage_mhcc"  # MHCC Heritage Clearance
    TYPE_AVIATION_AAI = "aviation_aai"  # AAI / Aviation Clearance
    TYPE_POLLUTION_MPCB = "pollution_mpcb"  # MPCB Pollution Control Clearance
    TYPE_CHOICES = [
        (TYPE_RAILWAY, "Railway Authority NOC"),
        (TYPE_CRZ, "CRZ / MCZMA Coastal Clearance"),
        (TYPE_HERITAGE_MHCC, "MHCC Heritage Clearance"),
        (TYPE_AVIATION_AAI, "AAI / Aviation Clearance"),
        (TYPE_POLLUTION_MPCB, "MPCB Pollution Control Clearance"),
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
    # Evidence document attached when the clearance is fulfilled.
    # Nullable until fulfilled; required by fulfill_clearance() at service level.
    clearance_doc = models.ForeignKey(
        "documents.DocumentUpload",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="clearance_evidence",
    )
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


class ErasureRequest(models.Model):
    """
    AC-32 — DPDP Act erasure (right-to-be-forgotten) request.

    DPDP Rule 14 grants the Data Principal a statutory response window. We record
    ``due_at = requested_at + RESPONSE_WINDOW_DAYS`` so an overdue request is
    queryable and reportable.

    Erasure here means *anonymisation* of the subject's PII, not row deletion:
    Applications, fee assessments, certificates, and the append-only AuditEvent
    log are retained as legally required, while the ApplicantProfile's identifying
    fields are scrubbed. A request may be rejected when an active statutory process
    (an in-flight application) requires the data to be retained.
    """

    RESPONSE_WINDOW_DAYS = 90

    STATUS_PENDING = "pending"
    STATUS_COMPLETED = "completed"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_REJECTED, "Rejected"),
    ]

    # The Data Principal whose data is to be erased.
    subject = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="erasure_requests",
    )
    # Who lodged the request (usually the subject themselves; an admin may file
    # on their behalf). Kept separate from `subject` for audit clarity.
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="filed_erasure_requests",
    )
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)
    # Statutory deadline = requested_at + RESPONSE_WINDOW_DAYS, set in the service.
    due_at = models.DateTimeField()
    processed_at = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="processed_erasure_requests",
    )
    # Officer note on completion, or the reason an erasure was lawfully refused.
    resolution_notes = models.TextField(blank=True)

    class Meta:
        db_table = "compliance_erasure_request"
        indexes = [
            models.Index(fields=["status", "due_at"]),
            models.Index(fields=["subject", "status"]),
        ]
        ordering = ["-requested_at"]

    def __str__(self):
        return f"ErasureRequest({self.subject_id}, {self.status})"

    @property
    def is_overdue(self) -> bool:
        from django.utils import timezone

        return self.status == self.STATUS_PENDING and timezone.now() > self.due_at


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
