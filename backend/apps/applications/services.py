from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import (
    Application,
    ApplicationCounter,
    ApplicationParty,
    MilestoneInstance,
    StreamMilestone,
)

User = get_user_model()


def generate_application_number(year: int | None = None, prefix: str = "MBPASPA") -> str:
    """
    Return the next gapless application number for the given calendar year.

    Uses SELECT FOR UPDATE on ApplicationCounter so concurrent submissions
    within the same year serialise here — no gaps, no duplicates.
    Must be called inside an open transaction (the caller's or an atomic block).

    Format: {prefix}{YYYY}{NNNN}  e.g. MBPASPA20260061
    """
    if year is None:
        year = timezone.now().astimezone().year

    with transaction.atomic():
        counter, _ = ApplicationCounter.objects.select_for_update().get_or_create(
            year=year,
            prefix=prefix,
            defaults={"next_value": 1},
        )
        number = f"{prefix}{year}{counter.next_value:04d}"
        counter.next_value += 1
        counter.save(update_fields=["next_value"])
    return number


@transaction.atomic
def create_application(
    *,
    stream_id: int,
    submitted_by: User,
    plpn: str = "",
    plot_area_sqm=None,
    proposed_bua_sqm=None,
    existing_bua_sqm=None,
    zonal_rrr=None,
) -> Application:
    """
    Create a new draft Application and its account-of-record ApplicationParty.
    Application number is blank until submit_application() is called.
    """
    application = Application.objects.create(
        stream_id=stream_id,
        submitted_by=submitted_by,
        status=Application.STATUS_DRAFT,
        plpn=plpn,
        plot_area_sqm=plot_area_sqm,
        proposed_bua_sqm=proposed_bua_sqm,
        existing_bua_sqm=existing_bua_sqm,
        zonal_rrr=zonal_rrr,
    )
    ApplicationParty.objects.create(
        application=application,
        user=submitted_by,
        party_role=ApplicationParty.ROLE_CO_OWNER,
        is_account_of_record=True,
        name=submitted_by.get_full_name() or submitted_by.username,
        email=submitted_by.email,
    )
    return application


@transaction.atomic
def submit_application(*, application_id: int, submitted_by: User) -> Application:
    """
    Transition a draft Application to SUBMITTED, assign a gapless application
    number, and create the sequence=1 MilestoneInstance for the stream.

    assigned_officer is set to the first active officer with the required role;
    if none exists it is left NULL (normal on a fresh environment).
    """
    from apps.compliance.services import compute_due_at, record_audit_event
    from apps.identity.models import OfficerProfile

    application = Application.objects.select_for_update().get(pk=application_id)
    if application.status != Application.STATUS_DRAFT:
        from apps.common.exceptions import DomainError

        raise DomainError(
            f"Application {application_id} is not in DRAFT status (current: {application.status})."
        )

    now = timezone.now()
    year = now.astimezone().year
    application.application_number = generate_application_number(year=year)
    application.status = Application.STATUS_SUBMITTED
    application.submitted_at = now
    application.save(update_fields=["application_number", "status", "submitted_at"])

    record_audit_event(
        verb="application.submitted",
        target_type="Application",
        target_id=application.pk,
        actor=submitted_by,
        payload={
            "application_number": application.application_number,
            "stream": application.stream.code,
        },
    )

    # Create the first milestone instance for this stream's sequence=1 milestone.
    try:
        sm = StreamMilestone.objects.select_related("milestone").get(
            stream=application.stream, sequence=1
        )
    except StreamMilestone.DoesNotExist:
        return application

    due_at = compute_due_at(now, sm.milestone.default_sla_working_days)

    # Find the first active officer with the required role; leave NULL if none.
    assigned_officer = None
    if sm.required_officer_role:
        officer_profile = (
            OfficerProfile.objects.filter(role=sm.required_officer_role, is_active_officer=True)
            .select_related("user")
            .first()
        )
        if officer_profile is not None:
            assigned_officer = officer_profile.user

    MilestoneInstance.objects.create(
        application=application,
        stream_milestone=sm,
        assigned_officer=assigned_officer,
        status=MilestoneInstance.STATUS_IN_PROGRESS,
        started_at=now,
        due_at=due_at,
    )
    return application


ACTION_APPROVE = "approve"
ACTION_RETURN_FOR_CORRECTION = "return_for_correction"
ACTION_REJECT = "reject"
VALID_ACTIONS = frozenset({ACTION_APPROVE, ACTION_RETURN_FOR_CORRECTION, ACTION_REJECT})


def _assign_officer_for_sm(sm: StreamMilestone):
    """Return the first active officer matching sm.required_officer_role, or None."""
    from apps.identity.models import OfficerProfile

    if not sm.required_officer_role:
        return None
    profile = (
        OfficerProfile.objects.filter(role=sm.required_officer_role, is_active_officer=True)
        .select_related("user")
        .first()
    )
    return profile.user if profile else None


_MILESTONE_CERT_MAP: dict[str, list[str]] = {
    "S1": ["aip"],
    "S2": ["development_permission", "commencement_plinth"],
    "S3": ["further_commencement"],
    "S4": ["commencement_80pct"],
    "S5": ["commencement_rem20"],
    "S6": ["building_completion"],
    "OC": ["oc"],
    "DEMO": ["demolition_clearance"],
}


def _issue_certificates_for_milestone(instance, stream_milestone, application, issued_by) -> None:
    # Deferred imports to avoid circular apps.applications ↔ apps.certificates.
    from apps.certificates.services import compile_final_dossier, generate_certificate

    milestone_code = stream_milestone.milestone.code
    cert_types = _MILESTONE_CERT_MAP.get(milestone_code, [])

    if milestone_code == "DEMO" and application.stream.code != "reerection":
        return

    for cert_type in cert_types:
        generate_certificate(application=application, cert_type=cert_type, issued_by=issued_by)

    if milestone_code == "OC":
        compile_final_dossier(application=application, triggered_by=issued_by)


@transaction.atomic
def transition_milestone(
    *,
    milestone_instance_id: int,
    action: str,
    acting_officer: User,
    decision_note: str = "",
    correction_reason: str = "",
) -> MilestoneInstance:
    """
    Advance, return, or reject a MilestoneInstance.

    AC-02: Uses select_for_update() to serialise concurrent transitions.
    AC-09: Refuses if acting_officer is an ApplicationParty.
    AC-29: Refuses if any prior-sequence milestone is not cleared (APPROVED/DEEMED).
    """
    from apps.applications.exceptions import (
        ConcurrentModificationError,
        InvalidTransitionError,
        SeparationOfDutiesError,
    )
    from apps.compliance.services import compute_due_at, record_audit_event

    if action not in VALID_ACTIONS:
        raise InvalidTransitionError(
            f"Unknown action {action!r}. Valid actions: {sorted(VALID_ACTIONS)}"
        )

    # AC-02: lock the row so concurrent requests serialise here.
    try:
        instance = (
            MilestoneInstance.objects.select_related(
                "application__stream", "stream_milestone__milestone"
            )
            .select_for_update()
            .get(pk=milestone_instance_id)
        )
    except MilestoneInstance.DoesNotExist:
        raise InvalidTransitionError(
            f"MilestoneInstance {milestone_instance_id} does not exist."
        ) from None

    # If the instance is already terminal, a concurrent request got here first.
    if instance.status not in (MilestoneInstance.STATUS_IN_PROGRESS,):
        raise ConcurrentModificationError(
            f"MilestoneInstance {milestone_instance_id} is already in status "
            f"{instance.status!r} — possibly processed by a concurrent request."
        )

    application = instance.application
    current_sm = instance.stream_milestone

    # AC-09: separation of duties — applicant-side parties may not act.
    if ApplicationParty.objects.filter(application=application, user=acting_officer).exists():
        raise SeparationOfDutiesError(
            "Acting officer is listed as an ApplicationParty on this application "
            "and may not act on its milestones (AC-09 separation of duties)."
        )

    # AC-29: strict sequencing — all prior milestones must be cleared first.
    prior_sms = StreamMilestone.objects.filter(
        stream=application.stream, sequence__lt=current_sm.sequence
    ).values_list("pk", flat=True)
    uncleared = MilestoneInstance.objects.filter(
        application=application,
        stream_milestone__in=prior_sms,
    ).exclude(status__in=(MilestoneInstance.STATUS_APPROVED, MilestoneInstance.STATUS_DEEMED))
    if uncleared.exists():
        raise InvalidTransitionError(
            "Cannot act on this milestone: one or more prior-sequence milestones "
            "are not yet cleared (AC-29 strict sequencing)."
        )

    now = timezone.now()

    if action == ACTION_APPROVE:
        instance.status = MilestoneInstance.STATUS_APPROVED
        instance.completed_at = now
        instance.officer_remarks = decision_note
        instance.save(update_fields=["status", "completed_at", "officer_remarks"])

        record_audit_event(
            verb="milestone.approved",
            target_type="MilestoneInstance",
            target_id=instance.pk,
            actor=acting_officer,
            payload={
                "application": application.application_number,
                "milestone": current_sm.milestone.code,
                "sequence": current_sm.sequence,
                "decision_note": decision_note,
            },
        )

        _issue_certificates_for_milestone(
            instance=instance,
            stream_milestone=current_sm,
            application=application,
            issued_by=acting_officer,
        )

        # Look for the next milestone in sequence.
        try:
            next_sm = StreamMilestone.objects.select_related("milestone").get(
                stream=application.stream, sequence=current_sm.sequence + 1
            )
        except StreamMilestone.DoesNotExist:
            # No next milestone — the application is fully approved.
            application.status = Application.STATUS_APPROVED
            application.save(update_fields=["status"])
        else:
            due_at = compute_due_at(now, next_sm.milestone.default_sla_working_days)
            MilestoneInstance.objects.create(
                application=application,
                stream_milestone=next_sm,
                assigned_officer=_assign_officer_for_sm(next_sm),
                status=MilestoneInstance.STATUS_IN_PROGRESS,
                started_at=now,
                due_at=due_at,
            )

    elif action == ACTION_RETURN_FOR_CORRECTION:
        instance.officer_remarks = correction_reason
        instance.save(update_fields=["officer_remarks"])

        record_audit_event(
            verb="milestone.returned_for_correction",
            target_type="MilestoneInstance",
            target_id=instance.pk,
            actor=acting_officer,
            payload={
                "application": application.application_number,
                "milestone": current_sm.milestone.code,
                "correction_reason": correction_reason,
            },
        )

    elif action == ACTION_REJECT:
        instance.status = MilestoneInstance.STATUS_REJECTED
        instance.completed_at = now
        instance.officer_remarks = decision_note
        instance.save(update_fields=["status", "completed_at", "officer_remarks"])

        application.status = Application.STATUS_REJECTED
        application.save(update_fields=["status"])

        record_audit_event(
            verb="milestone.rejected",
            target_type="MilestoneInstance",
            target_id=instance.pk,
            actor=acting_officer,
            payload={
                "application": application.application_number,
                "milestone": current_sm.milestone.code,
                "decision_note": decision_note,
            },
        )

    return instance


def assign_application_number(application: Application) -> Application:
    """
    Assign a gapless application number to a draft application on submission.
    Idempotent: if the application already has a number, it is returned unchanged.
    """
    if application.application_number:
        return application
    year = timezone.now().astimezone().year
    application.application_number = generate_application_number(year=year)
    application.save(update_fields=["application_number"])
    return application
