from django.conf import settings
from django.db import models


class Stream(models.Model):
    """One of the 7 permission streams (e.g. New Construction, Demolition, etc.)."""

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "applications_stream"

    def __str__(self):
        return self.name


class Milestone(models.Model):
    """A named review stage that exists independent of any stream (e.g. S1-RDO, S2, OC)."""

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    default_sla_working_days = models.PositiveSmallIntegerField(default=21)

    class Meta:
        db_table = "applications_milestone"

    def __str__(self):
        return self.code


class StreamMilestone(models.Model):
    """Ordered mapping of milestones within a stream."""

    stream = models.ForeignKey(Stream, on_delete=models.CASCADE, related_name="stream_milestones")
    milestone = models.ForeignKey(
        Milestone, on_delete=models.PROTECT, related_name="stream_milestones"
    )
    sequence = models.PositiveSmallIntegerField()
    # Safe default: opt-IN to deemed clearance by explicitly setting True.
    # Omitting this field always produces the safe (non-clearable) state.
    deemed_clearance_eligible = models.BooleanField(default=False)
    required_officer_role = models.CharField(max_length=20, blank=True)

    class Meta:
        db_table = "applications_stream_milestone"
        unique_together = [("stream", "sequence"), ("stream", "milestone")]
        ordering = ["stream", "sequence"]


class ApplicationCounter(models.Model):
    """
    Gapless sequence table per year. Rows are locked with select_for_update()
    before incrementing — never use F() updates here; the lock IS the primitive.
    """

    year = models.PositiveSmallIntegerField()
    prefix = models.CharField(max_length=20, default="MBPASPA")
    next_value = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "applications_counter"
        unique_together = [("year", "prefix")]


class Application(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_SUBMITTED = "submitted"
    STATUS_UNDER_SCRUTINY = "under_scrutiny"
    STATUS_AWAITING_NEXT = "awaiting_next_milestone"
    STATUS_REJECTED = "rejected"
    STATUS_APPROVED = "approved"
    STATUS_EXPIRED = "expired"
    STATUS_WITHDRAWN = "withdrawn"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_UNDER_SCRUTINY, "Under Scrutiny"),
        (STATUS_AWAITING_NEXT, "Awaiting Next Milestone"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_WITHDRAWN, "Withdrawn"),
    ]

    # Gapless application number: MBPASPA{YYYY}{NNNN} — assigned on submit, not create
    application_number = models.CharField(max_length=20, unique=True, blank=True, db_index=True)
    stream = models.ForeignKey(Stream, on_delete=models.PROTECT, related_name="applications")
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="submitted_applications"
    )
    status = models.CharField(
        max_length=30, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True
    )

    # Plot / land-plan details
    plpn = models.CharField(max_length=50, blank=True, verbose_name="Plot/Land Plan Number")
    plot_area_sqm = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    proposed_bua_sqm = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    existing_bua_sqm = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    # Zonal Ready Reckoner Rate — used for fee calculation
    zonal_rrr = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Soft-delete: statutory retention requirement; never hard-deleted
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "applications_application"
        indexes = [
            models.Index(fields=["submitted_by", "status"]),
            models.Index(fields=["stream", "status"]),
        ]

    def __str__(self):
        return self.application_number or f"Draft-{self.pk}"

    @property
    def is_deleted(self):
        return self.deleted_at is not None


class ApplicationParty(models.Model):
    """Additional parties on an application (architect, co-owner, legal rep, etc.)."""

    ROLE_ARCHITECT = "architect"
    ROLE_STRUCTURAL_ENGINEER = "structural_engineer"
    ROLE_CO_OWNER = "co_owner"
    ROLE_LEGAL_REP = "legal_rep"
    ROLE_CHOICES = [
        (ROLE_ARCHITECT, "Architect"),
        (ROLE_STRUCTURAL_ENGINEER, "Structural Engineer"),
        (ROLE_CO_OWNER, "Co-Owner"),
        (ROLE_LEGAL_REP, "Legal Representative"),
    ]

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="parties")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="application_parties",
        null=True,
        blank=True,
    )
    party_role = models.CharField(max_length=25, choices=ROLE_CHOICES)
    # True for the primary applicant account only; enforced via partial unique index in migration
    is_account_of_record = models.BooleanField(default=False)
    name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    mobile = models.CharField(max_length=15, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "applications_party"


class MilestoneInstance(models.Model):
    """One occurrence of a StreamMilestone in the lifecycle of an Application."""

    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name="milestone_instances"
    )
    stream_milestone = models.ForeignKey(StreamMilestone, on_delete=models.PROTECT)
    # Officer assigned at the time this milestone was created; SET_NULL if officer is deactivated
    assigned_officer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_milestones",
    )
    STATUS_PENDING = "pending"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_DEEMED = "deemed_cleared"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_DEEMED, "Deemed Cleared"),
    ]
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_PENDING)

    started_at = models.DateTimeField(null=True, blank=True)
    # SLA due date snapshot at the time this instance was created — not recalculated
    due_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    is_deemed = models.BooleanField(default=False)
    officer_remarks = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "applications_milestone_instance"
        indexes = [
            models.Index(fields=["application", "status"]),
            models.Index(fields=["assigned_officer", "status"]),
            models.Index(fields=["due_at"]),
        ]
