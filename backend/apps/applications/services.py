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
    from apps.compliance.services import compute_due_at
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
