from __future__ import annotations

import datetime
from datetime import timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import DomainError

from .models import AuditEvent, Complaint, ConditionalClearance, ErasureRequest

User = get_user_model()


def compute_due_at(started_at: datetime.datetime, working_days: int) -> datetime.datetime:
    """
    Return a timezone-aware datetime exactly `working_days` business days after
    `started_at`, skipping weekends (Sat/Sun) and any date present in the Holiday
    table (which includes 2nd/4th Saturdays per seed data).

    Loads all Holiday dates in a generous window up front to avoid N+1 queries.
    """
    from apps.compliance.models import Holiday

    start_date = started_at.date()
    # Load holiday dates in a window generous enough to cover any realistic SLA.
    window_end = start_date + timedelta(days=working_days * 3 + 30)
    holiday_dates: set[datetime.date] = set(
        Holiday.objects.filter(date__gte=start_date, date__lte=window_end).values_list(
            "date", flat=True
        )
    )

    current = start_date
    days_counted = 0
    while days_counted < working_days:
        current += timedelta(days=1)
        if current.weekday() >= 5:  # Saturday=5, Sunday=6
            continue
        if current in holiday_dates:
            continue
        days_counted += 1

    return started_at.replace(year=current.year, month=current.month, day=current.day)


def record_audit_event(
    *,
    verb: str,
    target_type: str,
    target_id: int,
    actor: User | None = None,
    payload: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str = "",
) -> AuditEvent:
    """
    Insert one immutable audit event. Never call .save()/.update() on the returned object.
    """
    return AuditEvent.objects.create(
        actor=actor,
        verb=verb,
        target_type=target_type,
        target_id=target_id,
        payload=payload or {},
        ip_address=ip_address,
        user_agent=user_agent,
    )


# ── AC-28 invariant helper ────────────────────────────────────────────────────


def _validate_complaint_raised_by(origin: str, raised_by: Any) -> None:
    """Enforce AC-28: raised_by is None iff origin == ORIGIN_SYSTEM."""
    if origin == Complaint.ORIGIN_APPLICANT and raised_by is None:
        raise DomainError("Applicant-raised complaints require a raised_by user (AC-28).")
    if origin == Complaint.ORIGIN_SYSTEM and raised_by is not None:
        raise DomainError("System-raised complaints must have raised_by=None (AC-28).")


# ── Complaint services ────────────────────────────────────────────────────────


@transaction.atomic
def raise_applicant_complaint(*, application, raised_by, subject: str, body: str) -> Complaint:
    _validate_complaint_raised_by(Complaint.ORIGIN_APPLICANT, raised_by)
    complaint = Complaint.objects.create(
        application=application,
        origin=Complaint.ORIGIN_APPLICANT,
        raised_by=raised_by,
        subject=subject,
        body=body,
    )
    record_audit_event(
        verb="complaint.raised",
        target_type="Complaint",
        target_id=complaint.pk,
        actor=raised_by,
        payload={
            "origin": Complaint.ORIGIN_APPLICANT,
            "subject": subject,
            "application": application.application_number,
        },
    )
    return complaint


@transaction.atomic
def raise_system_complaint(*, application, subject: str, body: str) -> Complaint:
    _validate_complaint_raised_by(Complaint.ORIGIN_SYSTEM, None)
    complaint = Complaint.objects.create(
        application=application,
        origin=Complaint.ORIGIN_SYSTEM,
        raised_by=None,
        subject=subject,
        body=body,
    )
    record_audit_event(
        verb="complaint.raised_by_system",
        target_type="Complaint",
        target_id=complaint.pk,
        payload={
            "origin": Complaint.ORIGIN_SYSTEM,
            "subject": subject,
            "application": application.application_number,
        },
    )
    return complaint


@transaction.atomic
def resolve_complaint(*, complaint: Complaint, resolved_by, resolution_notes: str) -> Complaint:
    if complaint.status == Complaint.STATUS_RESOLVED:
        raise DomainError("Complaint is already resolved.")
    complaint.status = Complaint.STATUS_RESOLVED
    complaint.resolution_notes = resolution_notes
    complaint.resolved_at = timezone.now()
    complaint.save(update_fields=["status", "resolution_notes", "resolved_at"])
    record_audit_event(
        verb="complaint.resolved",
        target_type="Complaint",
        target_id=complaint.pk,
        actor=resolved_by,
        payload={"resolution_notes": resolution_notes},
    )
    return complaint


# ── ConditionalClearance services ─────────────────────────────────────────────


@transaction.atomic
def create_conditional_clearance(
    *,
    application,
    milestone_instance,
    clearance_type: str,
    description: str,
    trigger_metadata: dict,
    created_by,
) -> ConditionalClearance:
    clearance = ConditionalClearance.objects.create(
        application=application,
        milestone_instance=milestone_instance,
        clearance_type=clearance_type,
        description=description,
        trigger_metadata=trigger_metadata,
    )
    record_audit_event(
        verb="clearance.created",
        target_type="ConditionalClearance",
        target_id=clearance.pk,
        actor=created_by,
        payload={
            "clearance_type": clearance_type,
            "application": application.application_number,
        },
    )
    return clearance


# ── DPDP erasure services (AC-32) ─────────────────────────────────────────────

# Application statuses that represent an in-flight statutory process; while any
# exist for the subject, the underlying PII must be retained (lawful exception to
# erasure under DPDP) and the request is rejected rather than completed.
_ACTIVE_APPLICATION_STATUSES = (
    "draft",
    "submitted",
    "under_scrutiny",
    "awaiting_next_milestone",
)


@transaction.atomic
def create_erasure_request(*, subject, requested_by, reason: str = "") -> ErasureRequest:
    """
    Lodge a DPDP erasure request. ``due_at`` is set to the statutory response
    window (RESPONSE_WINDOW_DAYS) from now so overdue requests are queryable.
    """
    now = timezone.now()
    req = ErasureRequest.objects.create(
        subject=subject,
        requested_by=requested_by,
        reason=reason,
        status=ErasureRequest.STATUS_PENDING,
        due_at=now + timedelta(days=ErasureRequest.RESPONSE_WINDOW_DAYS),
    )
    record_audit_event(
        verb="erasure.requested",
        target_type="ErasureRequest",
        target_id=req.pk,
        actor=requested_by,
        payload={
            "subject_id": subject.pk,
            "due_at": req.due_at.isoformat(),
        },
    )
    return req


def _subject_has_active_applications(subject) -> bool:
    """True if the subject owns or is a party to any in-flight application."""
    from apps.applications.models import Application, ApplicationParty

    if Application.objects.filter(
        submitted_by=subject, status__in=_ACTIVE_APPLICATION_STATUSES
    ).exists():
        return True
    return ApplicationParty.objects.filter(
        user=subject, application__status__in=_ACTIVE_APPLICATION_STATUSES
    ).exists()


def _anonymise_subject(subject) -> None:
    """
    Scrub the subject's PII in place. Retains the User and ApplicantProfile rows
    (FKs from Applications/AuditEvent are PROTECT) but removes identifying data.
    """
    from apps.identity.models import ApplicantProfile

    ApplicantProfile.objects.filter(user=subject).update(
        full_name="[ERASED]",
        pan_number="",
        aadhaar_hash="",
        aadhaar_last4="",
        address="",
    )

    subject.first_name = ""
    subject.last_name = ""
    subject.email = f"erased.user.{subject.pk}@erased.invalid"
    subject.username = f"erased_user_{subject.pk}"
    subject.mobile = ""
    subject.is_mobile_verified = False
    subject.is_active = False
    subject.set_unusable_password()
    subject.save(
        update_fields=[
            "first_name",
            "last_name",
            "email",
            "username",
            "mobile",
            "is_mobile_verified",
            "is_active",
            "password",
        ]
    )

    # Invalidate any outstanding OTP tokens for the subject.
    from apps.identity.models import OtpToken

    OtpToken.objects.filter(user=subject, consumed_at__isnull=True).update(
        consumed_at=timezone.now()
    )


@transaction.atomic
def process_erasure_request(
    *, erasure_request: ErasureRequest, processed_by, approve: bool, resolution_notes: str = ""
) -> ErasureRequest:
    """
    Complete or reject a pending erasure request.

    On approval: refuses (rejects) if the subject has active applications whose
    data must be retained for the ongoing statutory process; otherwise anonymises
    the subject's PII and marks the request completed. Either outcome is audited.
    """
    if erasure_request.status != ErasureRequest.STATUS_PENDING:
        raise DomainError("Erasure request is already processed.")

    subject = erasure_request.subject
    now = timezone.now()

    if approve and _subject_has_active_applications(subject):
        raise DomainError(
            "Cannot erase: subject has active applications whose data must be "
            "retained for the ongoing statutory process (DPDP lawful-retention "
            "exception). Reject the request with this reason, or wait until the "
            "applications reach a terminal state."
        )

    if approve:
        _anonymise_subject(subject)
        erasure_request.status = ErasureRequest.STATUS_COMPLETED
        verb = "erasure.completed"
    else:
        erasure_request.status = ErasureRequest.STATUS_REJECTED
        verb = "erasure.rejected"

    erasure_request.processed_at = now
    erasure_request.processed_by = processed_by
    erasure_request.resolution_notes = resolution_notes
    erasure_request.save(
        update_fields=["status", "processed_at", "processed_by", "resolution_notes"]
    )

    record_audit_event(
        verb=verb,
        target_type="ErasureRequest",
        target_id=erasure_request.pk,
        actor=processed_by,
        payload={
            "subject_id": subject.pk,
            "resolution_notes": resolution_notes,
        },
    )
    return erasure_request


@transaction.atomic
def fulfill_clearance(
    *, clearance: ConditionalClearance, clearance_doc, fulfilled_by
) -> ConditionalClearance:
    if clearance.is_fulfilled:
        raise DomainError("Clearance is already fulfilled.")
    clearance.is_fulfilled = True
    clearance.fulfilled_at = timezone.now()
    clearance.fulfilled_by = fulfilled_by
    clearance.clearance_doc = clearance_doc
    clearance.save(
        update_fields=["is_fulfilled", "fulfilled_at", "fulfilled_by_id", "clearance_doc_id"]
    )
    record_audit_event(
        verb="clearance.fulfilled",
        target_type="ConditionalClearance",
        target_id=clearance.pk,
        actor=fulfilled_by,
        payload={
            "clearance_type": clearance.clearance_type,
            "clearance_doc_id": clearance_doc.pk,
            "application": clearance.application.application_number,
        },
    )
    return clearance
